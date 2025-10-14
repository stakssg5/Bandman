#!/usr/bin/env python3
"""
Bitcoin wallet address scanner for files and directories.

- Detects and validates:
  - Legacy Base58Check (P2PKH, P2SH) addresses
  - Bech32/Bech32m SegWit addresses (bc1/tb1/bcrt1; v0/v1+)
- Recursively scans directories with sensible defaults
- Skips very large files by default
- Optional JSON output for automation

Usage examples:
  python btc_wallet_scanner.py .
  python btc_wallet_scanner.py /path/to/file.txt
  python btc_wallet_scanner.py . --json > results.json
  python btc_wallet_scanner.py . --exclude node_modules --exclude .git --max-file-size 10MB

No third-party dependencies; Python 3.8+ recommended.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


# ----------------------------- Base58Check utils -----------------------------
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX: Dict[str, int] = {ch: i for i, ch in enumerate(BASE58_ALPHABET)}


def _double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def decode_base58(s: str) -> Optional[bytes]:
    value = 0
    for ch in s:
        digit = _BASE58_INDEX.get(ch)
        if digit is None:
            return None
        value = value * 58 + digit
    # Convert integer to bytes without leading sign; handle leading zeros
    full_bytes = value.to_bytes((value.bit_length() + 7) // 8 or 1, "big")
    n_leading = len(s) - len(s.lstrip("1"))
    return b"\x00" * n_leading + full_bytes


def decode_base58_check(s: str) -> Optional[Tuple[int, bytes]]:
    raw = decode_base58(s)
    if raw is None or len(raw) < 5:
        return None
    payload, checksum = raw[:-4], raw[-4:]
    if _double_sha256(payload)[:4] != checksum:
        return None
    version = payload[0]
    data = payload[1:]
    return version, data


# Base58 mainnet/testnet version bytes for Bitcoin addresses
BASE58_VERSION_TO_KIND_NETWORK: Dict[int, Tuple[str, str]] = {
    0x00: ("P2PKH", "mainnet"),  # 1...
    0x05: ("P2SH", "mainnet"),   # 3...
    0x6F: ("P2PKH", "testnet"),  # m/n...
    0xC4: ("P2SH", "testnet"),   # 2...
}


# ------------------------------- Bech32 utils -------------------------------
# BIP-173/350 reference-style implementation
BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_INDEX: Dict[str, int] = {c: i for i, c in enumerate(BECH32_CHARSET)}
_GEN = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)


@dataclass
class Bech32Decoded:
    hrp: str
    data: List[int]
    encoding: str  # "bech32" or "bech32m"


def _hrp_expand(hrp: str) -> List[int]:
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _polymod(values: Iterable[int]) -> int:
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            if (b >> i) & 1:
                chk ^= _GEN[i]
    return chk


def _bech32_verify_checksum(hrp: str, data: List[int]) -> Optional[str]:
    const_bech32 = 1
    const_bech32m = 0x2bc830a3
    polymod = _polymod(_hrp_expand(hrp) + data)
    if polymod == const_bech32:
        return "bech32"
    if polymod == const_bech32m:
        return "bech32m"
    return None


def bech32_decode(addr: str) -> Optional[Bech32Decoded]:
    if any(ord(x) < 33 or ord(x) > 126 for x in addr):
        return None
    # Reject mixed case
    if addr.lower() != addr and addr.upper() != addr:
        return None
    addr = addr.lower()
    if addr.rfind("1") == -1:
        return None
    pos = addr.rfind("1")
    hrp = addr[:pos]
    data_part = addr[pos + 1 :]
    if len(hrp) < 1 or len(data_part) < 6:
        return None
    try:
        data = [
            _BECH32_INDEX[ch] if ch in _BECH32_INDEX else -1 for ch in data_part
        ]
    except Exception:
        return None
    if any(v == -1 for v in data):
        return None
    enc = _bech32_verify_checksum(hrp, data)
    if enc is None:
        return None
    # Exclude the 6 checksum values; return data without checksum
    return Bech32Decoded(hrp=hrp, data=data[:-6], encoding=enc)


def _convertbits(data: Sequence[int], from_bits: int, to_bits: int, pad: bool) -> Optional[List[int]]:
    acc = 0
    bits = 0
    ret: List[int] = []
    maxv = (1 << to_bits) - 1
    max_acc = (1 << (from_bits + to_bits - 1)) - 1
    for value in data:
        if value < 0 or value >> from_bits:
            return None
        acc = ((acc << from_bits) | value) & max_acc
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (to_bits - bits)) & maxv)
    elif bits >= from_bits or ((acc << (to_bits - bits)) & maxv):
        return None
    return ret


@dataclass
class SegwitDecoded:
    hrp: str
    version: int
    program: bytes
    encoding: str  # "bech32" or "bech32m"


def decode_segwit_address(addr: str) -> Optional[SegwitDecoded]:
    dec = bech32_decode(addr)
    if dec is None:
        return None
    if dec.hrp not in ("bc", "tb", "bcrt"):
        return None
    if not dec.data:
        return None
    version = dec.data[0]
    if version < 0 or version > 16:
        return None
    prog5 = dec.data[1:]
    prog8 = _convertbits(prog5, 5, 8, False)
    if prog8 is None:
        return None
    program = bytes(prog8)
    if len(program) < 2 or len(program) > 40:
        return None
    # Validation per BIP-173/350
    if version == 0:
        if dec.encoding != "bech32":
            return None
        if len(program) not in (20, 32):
            return None
    else:
        if dec.encoding != "bech32m":
            return None
    return SegwitDecoded(hrp=dec.hrp, version=version, program=program, encoding=dec.encoding)


# ------------------------------- Regex patterns ------------------------------
# Note: Regex finds candidates; we then fully validate.
BASE58_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9])[123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz]{26,35}(?![A-Za-z0-9])"
)

# Bech32 valid charset and reasonable length (max 90 total, so post-hrp+1 up to ~83)
BECH32_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:bc1|tb1|bcrt1)[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{11,83}(?![A-Za-z0-9])",
    re.IGNORECASE,
)


# ------------------------------ Scanning helpers -----------------------------
@dataclass
class MatchResult:
    address: str
    kind: str  # base58 or bech32
    variant: str  # P2PKH/P2SH/P2WPKH/P2WSH/Taproot/SegWit
    network: str  # mainnet/testnet/regtest/unknown
    file_path: str
    line: int
    col: int
    context: str


def _is_probably_binary(sample: bytes) -> bool:
    if not sample:
        return False
    # Heuristic: null bytes or high non-text ratio
    if b"\x00" in sample:
        return True
    text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x7F)))
    nontext = sum(b not in text_chars for b in sample)
    return nontext / max(1, len(sample)) > 0.30


def _filesize(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


def _read_text(path: str, max_bytes: int) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            data = f.read(max_bytes)
    except (OSError, IOError):
        return None
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return None


def _extract_context(text: str, start: int, end: int, span: int = 40) -> str:
    lo = max(0, start - span)
    hi = min(len(text), end + span)
    ctx = text[lo:hi]
    ctx = ctx.replace("\n", " ")
    return ctx


def _line_col_from_offset(text: str, offset: int) -> Tuple[int, int]:
    # 1-based line and column
    line = text.count("\n", 0, offset) + 1
    last_nl = text.rfind("\n", 0, offset)
    col = offset - (last_nl + 1) + 1
    return line, col


def _validate_base58(addr: str) -> Optional[Tuple[str, str]]:
    decoded = decode_base58_check(addr)
    if decoded is None:
        return None
    version, _payload = decoded
    kind_net = BASE58_VERSION_TO_KIND_NETWORK.get(version)
    if not kind_net:
        return None
    return kind_net  # (variant, network)


def _validate_bech32(addr: str) -> Optional[Tuple[str, str, str]]:
    segwit = decode_segwit_address(addr)
    if segwit is None:
        return None
    network = {"bc": "mainnet", "tb": "testnet", "bcrt": "regtest"}[segwit.hrp]
    if segwit.version == 0 and len(segwit.program) == 20:
        variant = "P2WPKH"
    elif segwit.version == 0 and len(segwit.program) == 32:
        variant = "P2WSH"
    elif segwit.version == 1 and len(segwit.program) == 32:
        variant = "Taproot"
    else:
        variant = f"SegWitV{segwit.version}"
    return segwit.encoding, network, variant


def find_addresses_in_text(text: str) -> List[Tuple[re.Match[str], MatchResult]]:
    results: List[Tuple[re.Match[str], MatchResult]] = []
    seen_spans: set = set()

    # Base58 candidates
    for m in BASE58_CANDIDATE_RE.finditer(text):
        addr = m.group(0)
        validated = _validate_base58(addr)
        if not validated:
            continue
        variant, network = validated
        if (m.start(), m.end()) in seen_spans:
            continue
        seen_spans.add((m.start(), m.end()))
        line, col = _line_col_from_offset(text, m.start())
        ctx = _extract_context(text, m.start(), m.end())
        results.append(
            (
                m,
                MatchResult(
                    address=addr,
                    kind="base58",
                    variant=variant,
                    network=network,
                    file_path="",
                    line=line,
                    col=col,
                    context=ctx,
                ),
            )
        )

    # Bech32 candidates (case-insensitive)
    for m in BECH32_CANDIDATE_RE.finditer(text):
        addr_raw = m.group(0)
        # Normalize to lowercase for validation; reject mixed case is already enforced in bech32_decode
        addr = addr_raw.lower()
        # Hard length cap per BIP-173 (90 chars)
        if len(addr) > 90:
            continue
        validated = _validate_bech32(addr)
        if not validated:
            continue
        encoding, network, variant = validated
        if (m.start(), m.end()) in seen_spans:
            continue
        seen_spans.add((m.start(), m.end()))
        line, col = _line_col_from_offset(text, m.start())
        ctx = _extract_context(text, m.start(), m.end())
        results.append(
            (
                m,
                MatchResult(
                    address=addr_raw,
                    kind=f"bech32:{encoding}",
                    variant=variant,
                    network=network,
                    file_path="",
                    line=line,
                    col=col,
                    context=ctx,
                ),
            )
        )

    return results


def scan_file(path: str, max_bytes: int, skip_binary: bool) -> List[MatchResult]:
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
            if skip_binary and _is_probably_binary(head):
                return []
            # Read entire file up to max_bytes
            remaining = max_bytes - len(head)
            if remaining < 0:
                remaining = 0
            rest = f.read(remaining)
            data = head + rest
    except (OSError, IOError):
        return []

    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:
        return []

    matches = find_addresses_in_text(text)
    results: List[MatchResult] = []
    for _m, res in matches:
        results.append(
            MatchResult(
                address=res.address,
                kind=res.kind,
                variant=res.variant,
                network=res.network,
                file_path=path,
                line=res.line,
                col=res.col,
                context=res.context,
            )
        )
    return results


DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "vendor",
    ".tox",
    ".venv",
    "venv",
    "build",
    "dist",
    ".next",
    "target",
}


def _should_exclude(path: str, exclude_names: set) -> bool:
    base = os.path.basename(path)
    return base in exclude_names


def parse_size(size_str: str) -> int:
    s = size_str.strip().upper()
    units = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}
    if s.endswith(tuple(units.keys())):
        for u, m in units.items():
            if s.endswith(u):
                num = float(s[: -len(u)].strip())
                return int(num * m)
    # plain bytes
    return int(float(s))


def walk_paths(root: str, exclude: Sequence[str]) -> Iterator[str]:
    exclude_set = set(exclude)
    if os.path.isfile(root):
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        # In-place prune excluded directories
        dirnames[:] = [d for d in dirnames if not _should_exclude(d, exclude_set)]
        for name in filenames:
            yield os.path.join(dirpath, name)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan files/dirs for valid Bitcoin wallet addresses",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="File or directory to scan (use - for stdin)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_out",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--max-file-size",
        default="5MB",
        help="Maximum file size to read per file",
    )
    parser.add_argument(
        "--include-binary",
        action="store_true",
        help="Scan binary files as well (may be slower, more noise)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Directory names to exclude during recursion (can be given multiple times)",
    )

    args = parser.parse_args(argv)

    exclude = set(DEFAULT_EXCLUDED_DIRS)
    if args.exclude:
        exclude.update(args.exclude)

    try:
        max_bytes = parse_size(args.max_file_size)
    except Exception:
        print("Invalid --max-file-size. Use e.g. 5MB, 200KB, 1000000", file=sys.stderr)
        return 2

    results: List[MatchResult] = []

    if args.path == "-":
        data = sys.stdin.buffer.read(max_bytes)
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            text = ""
        for _m, res in find_addresses_in_text(text):
            results.append(
                MatchResult(
                    address=res.address,
                    kind=res.kind,
                    variant=res.variant,
                    network=res.network,
                    file_path="<stdin>",
                    line=res.line,
                    col=res.col,
                    context=res.context,
                )
            )
    else:
        root = os.path.abspath(args.path)
        files = list(walk_paths(root, exclude))
        for fp in files:
            size = _filesize(fp)
            if size != -1 and size > max_bytes:
                continue
            file_results = scan_file(fp, max_bytes=max_bytes, skip_binary=not args.include_binary)
            results.extend(file_results)

    if args.json_out:
        out = [
            {
                "address": r.address,
                "kind": r.kind,
                "variant": r.variant,
                "network": r.network,
                "file": r.file_path,
                "line": r.line,
                "col": r.col,
                "context": r.context,
            }
            for r in results
        ]
        json.dump(out, sys.stdout, indent=2)
        print()
    else:
        if not results:
            print("No Bitcoin addresses found.")
        else:
            for r in results:
                print(
                    f"{r.file_path}:{r.line}:{r.col}  {r.address}  [{r.kind} {r.variant} {r.network}]"
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
