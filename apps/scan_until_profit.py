#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
import os

# Ensure repository root is on sys.path so local package imports work when
# running via absolute script path or frozen executables.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from typing import Iterable, List, Sequence, Tuple

from wallet_checker.checkers import get_checker_for_chain, BalanceResult
from wallet_checker.config import get_chain_registry


DEFAULT_DEMO_ADDRESSES: List[str] = [
    # ETH/EVM demo addresses (public, well‑known)
    "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe",
    "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
    # BTC sample (random example format; replace as desired)
    "bc1qw4yq0w6yq7w4q2e7krq6t8g0rjhs0f0y7z6e9k",
    # Tron
    "TQ5Cw1hF4u8q7aVJvWq6yC2A9L1mQ2N9Xh",
]

DEFAULT_CHAINS: Sequence[str] = ("eth", "polygon", "bsc", "op", "btc", "tron")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Continuously scan balances across chains and addresses until a positive balance is found.\n"
            "By default uses public demo addresses and public RPCs."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--chains",
        default=",".join(DEFAULT_CHAINS),
        help="Comma‑separated list of chain keys to scan (e.g. eth,btc,tron)",
    )
    p.add_argument(
        "--addresses",
        default=None,
        help="Comma‑separated list of addresses to scan",
    )
    p.add_argument(
        "--file",
        default=None,
        help="Path to file with one address per line",
    )
    p.add_argument(
        "--sleep-ms",
        type=int,
        default=250,
        help="Sleep between requests (throttle public endpoints)",
    )
    p.add_argument(
        "--max-checks",
        type=int,
        default=0,
        help="Optional limit for number of checks before exiting (0 = unlimited)",
    )
    return p.parse_args(argv)


def load_addresses(addresses_csv: str | None, file_path: str | None) -> List[str]:
    if addresses_csv:
        items = [a.strip() for a in addresses_csv.split(",") if a.strip()]
        if items:
            return items
    if file_path:
        path = Path(file_path)
        if not path.exists():
            raise SystemExit(f"Address file not found: {file_path}")
        items: List[str] = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            items.append(line)
        if items:
            return items
    return list(DEFAULT_DEMO_ADDRESSES)


def iter_chain_address_pairs(chain_keys: Sequence[str], addresses: Sequence[str]) -> Iterable[Tuple[str, str]]:
    # simple round‑robin over addresses then chains
    while True:
        for addr in addresses:
            for chain in chain_keys:
                yield chain, addr


def parse_display_to_float(display: str) -> float:
    # Many checkers emit a numeric value at the front of display; best‑effort parse
    try:
        token = display.strip().split()[0]
        return float(token)
    except Exception:
        return 0.0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    chain_keys = [c.strip().lower() for c in args.chains.split(",") if c.strip()]
    reg = get_chain_registry()
    for ck in chain_keys:
        if ck not in reg:
            raise SystemExit(f"Unknown chain key: {ck}. Known: {', '.join(sorted(reg.keys()))}")

    addresses = list(dict.fromkeys(load_addresses(args.addresses, args.file)))  # de‑dupe, preserve order
    if not addresses:
        raise SystemExit("No addresses to scan.")

    print(f"Scanning chains: {', '.join(chain_keys)}")
    print(f"Addresses: {len(addresses)} loaded")
    print("Press Ctrl+C to stop.\n")

    checks_done = 0
    started_at = time.time()

    try:
        for chain, addr in iter_chain_address_pairs(chain_keys, addresses):
            checker = get_checker_for_chain(chain)
            try:
                res: BalanceResult = checker(addr)
                value = parse_display_to_float(res.display)
                checks_done += 1
                print(f"[{checks_done:>7}] {chain}:{addr[:10]}… | {res.display}")
                if value > 0:
                    elapsed = time.time() - started_at
                    print("\n=== PROFIT FOUND ===")
                    print(f"Chain:    {chain}")
                    print(f"Address:  {addr}")
                    print(f"Balance:  {res.display}")
                    print(f"Checks:   {checks_done}")
                    print(f"Elapsed:  {elapsed:.2f}s")
                    return 0
            except KeyboardInterrupt:
                print("Interrupted by user.")
                return 130
            except Exception as exc:
                checks_done += 1
                print(f"[{checks_done:>7}] {chain}:{addr[:10]}… | error: {exc}")
            if args.sleep_ms:
                time.sleep(max(0.0, args.sleep_ms / 1000.0))
            if args.max_checks and checks_done >= args.max_checks:
                print("Reached max checks without finding positive balance.")
                return 1
    except KeyboardInterrupt:
        print("Interrupted by user.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
