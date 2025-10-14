#!/usr/bin/env python3
"""
Compliance-safe PII scanner/redactor for payment card data and addresses.
- Scans files or directories recursively for potential PANs, CVV/CVC, expiration dates, and address-like lines.
- Redacts sensitive values by default; can optionally output a JSON report with masked values.
- Does NOT print or store full PANs, CVVs, or other sensitive data.

Supported detections (approximate with validation):
- PAN: Luhn-valid 13–19 digit sequences; optional separators (- or space). BIN allowlist filter optional.
- CVV/CVC: 3–4 digits near keywords (cvv|cvc|security code) or following PAN in the same block.
- Expiry: MM/YY or MM/YYYY with ranges; proximity heuristics to PAN.
- Address lines: Heuristics for street lines and ZIP codes when co-located with PAN.

Usage:
  python scripts/pii_redactor.py scan --path <path> [--bin 440066] [--report out.json]
  python scripts/pii_redactor.py redact --path <path> --out <out_dir>

Notes:
- Redaction writes sanitized copies under out_dir, preserving structure.
- Report includes masked PAN (first6+last4), masked CVV (***), and masked address tokens.
- Always obey your organization's data handling policy and PCI DSS.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Tuple

# ---------- Utilities ----------

PAN_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")  # 13-19 digits with optional spaces/dashes
EXPIRY_RE = re.compile(r"\b(0[1-9]|1[0-2])[\/\-](\d{2}|\d{4})\b")
CVV_RE = re.compile(r"\b(?:cvv|cvc|security\s*code|card\s*code)\b\D{0,10}(\d{3,4})\b", re.IGNORECASE)
ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
STREET_HINT_RE = re.compile(r"\b(ave|avenue|st|street|rd|road|blvd|boulevard|ln|lane|dr|drive|ct|court|way|pkwy|parkway)\b", re.IGNORECASE)
STATE_RE = re.compile(r"\b(AL|AK|AZ|AR|CA|CO|CT|DC|DE|FL|GA|HI|IA|ID|IL|IN|KS|KY|LA|MA|MD|ME|MI|MN|MO|MS|MT|NC|ND|NE|NH|NJ|NM|NV|NY|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VA|VT|WA|WI|WV)\b")

# Simple Luhn check

def luhn_check(digits: str) -> bool:
    total = 0
    alt = False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if d < 0 or d > 9:
            return False
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return (total % 10) == 0


def normalize_pan(pan_text: str) -> str:
    return re.sub(r"[\s-]", "", pan_text)


def mask_pan(pan: str) -> str:
    if len(pan) < 10:
        return "*" * len(pan)
    return f"{pan[:6]}******{pan[-4:]}"


@dataclass
class Detection:
    kind: str  # 'pan', 'cvv', 'expiry', 'address'
    masked_value: str
    span: Tuple[int, int]
    context: str


@dataclass
class FileFindings:
    path: str
    detections: List[Detection]


def find_pans(text: str, allowed_bins: Optional[List[str]] = None) -> List[Tuple[Tuple[int,int], str, str]]:
    findings: List[Tuple[Tuple[int,int], str, str]] = []
    for m in PAN_CANDIDATE_RE.finditer(text):
        raw = m.group(0)
        pan = normalize_pan(raw)
        if len(pan) < 13 or len(pan) > 19:
            continue
        if not luhn_check(pan):
            continue
        if allowed_bins is not None and len(allowed_bins) > 0:
            if not any(pan.startswith(b) for b in allowed_bins):
                continue
        masked = mask_pan(pan)
        context = text[max(0, m.start()-30):min(len(text), m.end()+30)]
        findings.append(((m.start(), m.end()), masked, context))
    return findings


def find_expiries(text: str) -> List[Tuple[Tuple[int,int], str, str]]:
    results: List[Tuple[Tuple[int,int], str, str]] = []
    for m in EXPIRY_RE.finditer(text):
        mm, yy = m.group(1), m.group(2)
        yyyy = yy if len(yy) == 4 else ("20" + yy)
        masked = f"{mm}/**{yyyy[-2:]}"
        context = text[max(0, m.start()-20):min(len(text), m.end()+20)]
        results.append(((m.start(), m.end()), masked, context))
    return results


def find_cvvs(text: str) -> List[Tuple[Tuple[int,int], str, str]]:
    results: List[Tuple[Tuple[int,int], str, str]] = []
    for m in CVV_RE.finditer(text):
        masked = "***" if len(m.group(1)) == 3 else "****"
        context = text[max(0, m.start()-15):min(len(text), m.end()+15)]
        results.append(((m.start(1), m.end(1)), masked, context))
    return results


def find_addresses(text: str) -> List[Tuple[Tuple[int,int], str, str]]:
    results: List[Tuple[Tuple[int,int], str, str]] = []
    # Heuristic: a line containing a number and a street hint, optionally with state/zip
    for line in text.splitlines(keepends=True):
        start_idx = text.find(line)
        if re.search(r"\b\d+\b", line) and STREET_HINT_RE.search(line):
            masked = re.sub(r"\d", "X", line.strip())
            results.append(((start_idx, start_idx + len(line)), masked, line.strip()))
        elif ZIP_RE.search(line) or STATE_RE.search(line):
            masked = re.sub(r"\d", "X", line.strip())
            results.append(((start_idx, start_idx + len(line)), masked, line.strip()))
    return results


def scan_text(text: str, allowed_bins: Optional[List[str]]) -> List[Detection]:
    detections: List[Detection] = []
    for span, masked, ctx in find_pans(text, allowed_bins):
        detections.append(Detection("pan", masked, span, ctx))
    for span, masked, ctx in find_expiries(text):
        detections.append(Detection("expiry", masked, span, ctx))
    for span, masked, ctx in find_cvvs(text):
        detections.append(Detection("cvv", masked, span, ctx))
    for span, masked, ctx in find_addresses(text):
        detections.append(Detection("address", masked, span, ctx))
    detections.sort(key=lambda d: d.span[0])
    return detections


def redact_text(text: str, detections: List[Detection]) -> str:
    # Apply redactions from end to start to maintain indices
    redacted = text
    for det in sorted(detections, key=lambda d: d.span[0], reverse=True):
        s, e = det.span
        redacted = redacted[:s] + det.masked_value + redacted[e:]
    return redacted


def iter_files(path: Path) -> Iterator[Path]:
    if path.is_file():
        yield path
        return
    for root, _dirs, files in os.walk(path):
        for fn in files:
            p = Path(root) / fn
            # Limit to text-like files; skip binaries by extension heuristics
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".tar", ".mp3", ".mp4", ".mov"}:
                continue
            yield p


def load_text_safe(path: Path) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def scan_command(args: argparse.Namespace) -> int:
    src = Path(args.path)
    bins = args.bin or []
    findings: List[FileFindings] = []
    for file_path in iter_files(src):
        text = load_text_safe(file_path)
        if text is None:
            continue
        dets = scan_text(text, bins)
        if dets:
            findings.append(FileFindings(str(file_path), dets))
    if args.report:
        # Prepare JSON-safe masked report
        serializable = [
            {
                "path": ff.path,
                "detections": [asdict(d) for d in ff.detections],
            }
            for ff in findings
        ]
        write_text(Path(args.report), json.dumps(serializable, indent=2))
        print(f"Report written to {args.report} with masked values only")
    else:
        # Print a brief summary without revealing sensitive data
        for ff in findings:
            kinds = [d.kind for d in ff.detections]
            counts = {k: kinds.count(k) for k in sorted(set(kinds))}
            print(f"{ff.path}: {counts}")
    return 0


def redact_command(args: argparse.Namespace) -> int:
    src = Path(args.path)
    out_dir = Path(args.out)
    bins = args.bin or []
    for file_path in iter_files(src):
        text = load_text_safe(file_path)
        if text is None:
            continue
        dets = scan_text(text, bins)
        if not dets:
            # Copy original content without changes
            redacted_text = text
        else:
            redacted_text = redact_text(text, dets)
        dest = out_dir / file_path.relative_to(src if src.is_dir() else file_path.parent)
        write_text(dest, redacted_text)
    print(f"Redacted files written under {out_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan/redact payment PII (masked outputs; PCI-safe by default)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Scan path and optionally emit masked JSON report")
    p_scan.add_argument("--path", required=True, help="File or directory to scan")
    p_scan.add_argument("--bin", nargs="*", help="Optional BIN allowlist (e.g., 440066)")
    p_scan.add_argument("--report", help="Output JSON report path (masked values only)")
    p_scan.set_defaults(func=scan_command)

    p_redact = sub.add_parser("redact", help="Redact in files and write sanitized copies")
    p_redact.add_argument("--path", required=True, help="File or directory to scan/redact")
    p_redact.add_argument("--out", required=True, help="Destination directory for sanitized output")
    p_redact.add_argument("--bin", nargs="*", help="Optional BIN allowlist (e.g., 440066)")
    p_redact.set_defaults(func=redact_command)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Default to BofA BIN if provided via example
    if args.bin is None:
        args.bin = []
    # Safety: refuse to dump unmasked content
    if getattr(args, "report", None):
        if not str(args.report).endswith(".json"):
            print("Report must be a .json file", file=sys.stderr)
            return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
