#!/usr/bin/env python3
"""
Secure BTC wallet phrase scanner (single mnemonic) that derives common paths
and scans addresses until a non-zero balance is found.

- NO brute-force over multiple phrases. You must explicitly provide one mnemonic.
- Derivation standards: BIP44 (P2PKH), BIP49 (P2WPKH-in-P2SH),
  BIP84 (P2WPKH), BIP86 (P2TR/Taproot)
- Networks: mainnet, testnet
- Scans external chain by default (change chain optional)
- Stops on first funded address (confirmed or incl. mempool if configured)

Security note: Your mnemonic and (optional) passphrase are processed locally
and never transmitted. Only derived public addresses are queried via HTTP.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from getpass import getpass
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

try:
    from bip_utils import (
        Bip39SeedGenerator,
        Bip39MnemonicValidator,
        Bip44, Bip49, Bip84, Bip86,
        Bip44Coins, Bip49Coins, Bip84Coins, Bip86Coins,
        Bip44Changes,
    )
except Exception as e:  # pragma: no cover
    print(
        "bip_utils is required. Install with: pip install bip-utils",
        file=sys.stderr,
    )
    raise


DEFAULT_MAINNET_API = "https://mempool.space/api/"
DEFAULT_TESTNET_API = "https://mempool.space/testnet/api/"


@dataclass
class ScanFound:
    purpose: int
    account: int
    change: int
    index: int
    address: str
    address_type: str
    confirmed_sats: int
    mempool_delta_sats: int

    @property
    def total_incl_mempool_sats(self) -> int:
        return self.confirmed_sats + self.mempool_delta_sats


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Derive addresses from a mnemonic across common BTC paths and stop at first with balance."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    mn = parser.add_argument_group("Mnemonic")
    mn.add_argument("--mnemonic", help="BIP39 mnemonic (space-separated words)")
    mn.add_argument("--mnemonic-file", help="Path to file containing the mnemonic")
    mn.add_argument("--prompt-mnemonic", action="store_true", help="Securely prompt for mnemonic (hidden)")
    mn.add_argument("--passphrase", default=None, help="Optional BIP39 passphrase (NOT the 12/24 words)")
    mn.add_argument("--prompt-passphrase", action="store_true", help="Securely prompt for BIP39 passphrase (hidden)")

    net = parser.add_argument_group("Network/API")
    net.add_argument("--network", choices=["mainnet", "testnet"], default="mainnet")
    net.add_argument("--api-base", default=None, help="Override mempool.space API base URL")

    drv = parser.add_argument_group("Derivation")
    drv.add_argument(
        "--paths",
        default="84,86,49,44",
        help="Comma-separated purposes to scan (subset of 44,49,84,86)",
    )
    drv.add_argument("--account-start", type=int, default=0, help="Starting account index (inclusive)")
    drv.add_argument("--account-end", type=int, default=0, help="Ending account index (inclusive)")
    drv.add_argument("--start-index", type=int, default=0, help="Starting address index per chain")
    drv.add_argument(
        "--max-index",
        type=int,
        default=50,
        help="How many indices to scan per chain (from start-index)",
    )
    drv.add_argument("--include-change", action="store_true", help="Also scan change chain (1)")

    out = parser.add_argument_group("Scan behavior & Output")
    out.add_argument("--include-mempool", action="store_true", help="Consider mempool delta toward balance")
    out.add_argument("--min-balance-sats", type=int, default=1, help="Threshold to consider as found")
    out.add_argument("--verbose", action="store_true", help="Print progress to stderr")
    out.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds")
    out.add_argument("--format", choices=["pretty", "json"], default="pretty")

    return parser.parse_args(argv)


def resolve_api_base(network: str, api_base_override: Optional[str]) -> str:
    if api_base_override:
        return api_base_override.rstrip("/") + "/"
    return DEFAULT_TESTNET_API if network == "testnet" else DEFAULT_MAINNET_API


def read_mnemonic(args: argparse.Namespace) -> Tuple[str, Optional[str]]:
    if args.prompt_mnemonic:
        mnemonic = getpass("Enter mnemonic (hidden): ").strip()
    elif args.mnemonic_file:
        mnemonic = open(args.mnemonic_file, "r", encoding="utf-8").read().strip()
    elif args.mnemonic:
        mnemonic = args.mnemonic.strip()
    else:
        raise SystemExit("Provide --mnemonic, --mnemonic-file, or --prompt-mnemonic")

    passphrase: Optional[str]
    if args.prompt_passphrase:
        passphrase = getpass("Enter BIP39 passphrase (hidden, optional, press Enter if none): ")
    else:
        passphrase = args.passphrase

    mnemonic = " ".join(mnemonic.split())

    # Validate mnemonic
    try:
        Bip39MnemonicValidator(mnemonic).Validate()
    except Exception as e:
        raise SystemExit(f"Invalid mnemonic: {e}")

    return mnemonic, passphrase


def http_get_json(url: str, timeout: float) -> dict:
    req = Request(url, headers={"User-Agent": "btc-phrase-scanner/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            data = resp.read().decode(charset)
            return json.loads(data)
    except HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} for {url}") from e
    except URLError as e:
        raise RuntimeError(f"Network error for {url}: {e}") from e


def fetch_address_balance(api_base: str, address: str, timeout: float) -> Tuple[int, int]:
    info_url = urljoin(api_base, f"address/{address}")
    data = http_get_json(info_url, timeout=timeout)

    chain_stats = data.get("chain_stats", {})
    mempool_stats = data.get("mempool_stats", {})

    confirmed = int(chain_stats.get("funded_txo_sum", 0)) - int(chain_stats.get("spent_txo_sum", 0))
    mempool_delta = int(mempool_stats.get("funded_txo_sum", 0)) - int(mempool_stats.get("spent_txo_sum", 0))

    return confirmed, mempool_delta


def get_coin_enums(network: str) -> Tuple:
    if network == "testnet":
        return (
            Bip44Coins.BITCOIN_TESTNET,
            Bip49Coins.BITCOIN_TESTNET,
            Bip84Coins.BITCOIN_TESTNET,
            Bip86Coins.BITCOIN_TESTNET,
        )
    return (
        Bip44Coins.BITCOIN,
        Bip49Coins.BITCOIN,
        Bip84Coins.BITCOIN,
        Bip86Coins.BITCOIN,
    )


def build_contexts(seed_bytes: bytes, network: str) -> Dict[int, object]:
    c44, c49, c84, c86 = get_coin_enums(network)
    return {
        44: Bip44.FromSeed(seed_bytes, c44),
        49: Bip49.FromSeed(seed_bytes, c49),
        84: Bip84.FromSeed(seed_bytes, c84),
        86: Bip86.FromSeed(seed_bytes, c86),
    }


def derive_address(
    ctx_map: Dict[int, object],
    purpose: int,
    account: int,
    change: int,
    index: int,
) -> Tuple[str, str, str]:
    if purpose not in ctx_map:
        raise ValueError(f"Unsupported purpose: {purpose}")

    base = ctx_map[purpose]
    node = base.Purpose().Coin().Account(account).Change(
        Bip44Changes.CHAIN_EXT if change == 0 else Bip44Changes.CHAIN_INT
    ).AddressIndex(index)

    address = node.PublicKey().ToAddress()
    address_type = {44: "p2pkh", 49: "p2sh-p2wpkh", 84: "p2wpkh", 86: "p2tr"}[purpose]
    coin_type = 0 if isinstance(base, Bip44) or isinstance(base, Bip49) or isinstance(base, Bip84) or isinstance(base, Bip86) else 0
    # coin_type via SLIP-44 based on network; we infer by purpose contexts, but for reporting we use network-dependent value in path
    # We'll compute coin_type from the base coin configuration name
    try:
        # bip_utils exposes CoinConf.CoinNames().Name() like "Bitcoin" or "Bitcoin Testnet"
        is_testnet = "testnet" in base.CoinConf().CoinNames().Name().lower()
        coin_type = 1 if is_testnet else 0
    except Exception:
        coin_type = 0

    path = f"m/{purpose}'/{coin_type}'/{account}'/{change}/{index}"
    return address, path, address_type


def format_sats(sats: int) -> str:
    sign = "-" if sats < 0 else ""
    sats_abs = abs(sats)
    btc = sats_abs / 100_000_000
    return f"{sign}{sats_abs:,} sats ({sign}{btc:.8f} BTC)"


def scan_until_found(
    mnemonic: str,
    passphrase: Optional[str],
    network: str,
    purposes: List[int],
    account_start: int,
    account_end: int,
    start_index: int,
    max_index: int,
    include_change: bool,
    include_mempool: bool,
    min_balance_sats: int,
    api_base: str,
    timeout: float,
    verbose: bool,
) -> Optional[ScanFound]:
    seed_bytes = Bip39SeedGenerator(mnemonic).Generate(passphrase or "")
    ctx_map = build_contexts(seed_bytes, network)

    chains = [0, 1] if include_change else [0]

    for purpose in purposes:
        if purpose not in ctx_map:
            continue
        for account in range(account_start, account_end + 1):
            for change in chains:
                for idx in range(start_index, start_index + max_index):
                    address, path, addr_type = derive_address(ctx_map, purpose, account, change, idx)
                    if verbose:
                        print(f"Checking {address} at {path} ({addr_type})", file=sys.stderr)
                    confirmed, mempool_delta = fetch_address_balance(api_base, address, timeout)
                    total = confirmed + mempool_delta if include_mempool else confirmed
                    if total >= min_balance_sats:
                        return ScanFound(
                            purpose=purpose,
                            account=account,
                            change=change,
                            index=idx,
                            address=address,
                            address_type=addr_type,
                            confirmed_sats=confirmed,
                            mempool_delta_sats=mempool_delta,
                        )
    return None


def print_result(found: Optional[ScanFound], fmt: str, include_mempool: bool) -> int:
    if found is None:
        if fmt == "json":
            print(json.dumps({"found": False}, indent=2))
        else:
            print("No funded addresses found in scanned range.")
        return 2

    if fmt == "json":
        obj = {
            "found": True,
            "purpose": found.purpose,
            "derivation_path": f"m/{found.purpose}'/{{coin}}'/{found.account}'/{found.change}/{found.index}",
            "account": found.account,
            "change": found.change,
            "index": found.index,
            "address_type": found.address_type,
            "address": found.address,
            "confirmed_sats": found.confirmed_sats,
            "mempool_delta_sats": found.mempool_delta_sats,
            "total_incl_mempool_sats": found.total_incl_mempool_sats,
        }
        print(json.dumps(obj, indent=2))
        return 0

    # pretty
    print("Found funded address:")
    print(f"- Address: {found.address} [{found.address_type}]")
    print(f"- Path:    m/{found.purpose}'/{{coin}}'/{found.account}'/{found.change}/{found.index}")
    print(f"- Confirmed:     {format_sats(found.confirmed_sats)}")
    print(f"- Mempool Δ:     {format_sats(found.mempool_delta_sats)}")
    total = found.total_incl_mempool_sats if include_mempool else found.confirmed_sats
    print(f"- Total{' (incl. mempool)' if include_mempool else ''}: {format_sats(total)}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    mnemonic, passphrase = read_mnemonic(args)
    api_base = resolve_api_base(args.network, args.api_base)

    try:
        purposes = [int(p.strip()) for p in args.paths.split(",") if p.strip()]
    except ValueError:
        raise SystemExit("--paths must be a comma-separated list of integers like 84,86,49,44")

    found = scan_until_found(
        mnemonic=mnemonic,
        passphrase=passphrase,
        network=args.network,
        purposes=purposes,
        account_start=args.account_start,
        account_end=args.account_end,
        start_index=args.start_index,
        max_index=args.max_index,
        include_change=args.include_change,
        include_mempool=args.include_mempool,
        min_balance_sats=args.min_balance_sats,
        api_base=api_base,
        timeout=args.timeout,
        verbose=args.verbose,
    )

    return print_result(found, args.format, args.include_mempool)


if __name__ == "__main__":
    raise SystemExit(main())
