#!/usr/bin/env python3
"""
Bitcoin balance scanner across multiple wallets (address groups).

- Input: addresses via CLI, file (one per line), or JSON config with wallets
- API: Uses mempool.space HTTP API (mainnet or testnet)
- Output: table (default), json, or csv
- Concurrency: configurable thread pool

JSON config format example:
{
  "wallets": [
    {"name": "Cold Storage", "addresses": ["bc1...", "bc1..."]},
    {"name": "Hot Wallet",   "addresses": ["1...", "3..."]}
  ]
}

Note: This tool calculates balances using funded/spent stats from mempool.space.
Confirmed balance is chain_stats.funded_txo_sum - chain_stats.spent_txo_sum.
Mempool delta is mempool_stats.funded_txo_sum - mempool_stats.spent_txo_sum.
Total with mempool = confirmed + mempool_delta.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


DEFAULT_MAINNET_API = "https://mempool.space/api/"
DEFAULT_TESTNET_API = "https://mempool.space/testnet/api/"


@dataclass
class AddressBalance:
    address: str
    confirmed: int  # sats
    mempool_delta: int  # sats (can be negative)

    @property
    def total_including_mempool(self) -> int:
        return self.confirmed + self.mempool_delta


@dataclass
class WalletScanResult:
    name: str
    addresses: List[AddressBalance]

    @property
    def confirmed_total(self) -> int:
        return sum(a.confirmed for a in self.addresses)

    @property
    def mempool_delta_total(self) -> int:
        return sum(a.mempool_delta for a in self.addresses)

    @property
    def total_including_mempool(self) -> int:
        return self.confirmed_total + self.mempool_delta_total


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan Bitcoin balances for multiple addresses, grouped into wallets.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    src = parser.add_argument_group("Inputs")
    src.add_argument(
        "--addresses",
        help="Comma-separated list of addresses for a single wallet",
        default=None,
    )
    src.add_argument(
        "--file",
        help="Path to a text file with one address per line",
        default=None,
    )
    src.add_argument(
        "--config",
        help=(
            "Path to JSON config with wallets: { 'wallets': [ { 'name': 'X', 'addresses':[...]} ] }"
        ),
        default=None,
    )
    src.add_argument(
        "--wallet-name",
        help="Name used when --addresses/--file specify a single wallet",
        default="Default Wallet",
    )

    net = parser.add_argument_group("Network/API")
    net.add_argument(
        "--network",
        choices=["mainnet", "testnet"],
        default="mainnet",
        help="Bitcoin network to query",
    )
    net.add_argument(
        "--api-base",
        help="Override API base URL (advanced)",
        default=None,
    )

    run = parser.add_argument_group("Runtime")
    run.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Number of concurrent requests",
    )
    run.add_argument(
        "--rate-limit-ms",
        type=int,
        default=0,
        help="Optional sleep between requests per worker (ms)",
    )
    run.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Per-request timeout in seconds",
    )

    out = parser.add_argument_group("Output")
    out.add_argument(
        "--format",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format",
    )
    out.add_argument(
        "--include-mempool",
        action="store_true",
        help="Show totals including mempool deltas in summary",
    )
    out.add_argument(
        "--show-addresses",
        action="store_true",
        help="Include per-address rows/details in output",
    )

    args = parser.parse_args(argv)
    return args


def resolve_api_base(network: str, api_base_override: Optional[str]) -> str:
    if api_base_override:
        return api_base_override.rstrip("/") + "/"
    if network == "testnet":
        return DEFAULT_TESTNET_API
    return DEFAULT_MAINNET_API


def load_inputs(
    addresses_csv: Optional[str],
    file_path: Optional[str],
    config_path: Optional[str],
    single_wallet_name: str,
) -> List[Tuple[str, List[str]]]:
    """Return list of (wallet_name, addresses)."""
    if config_path:
        config = json.loads(Path(config_path).read_text())
        wallets = config.get("wallets", [])
        result: List[Tuple[str, List[str]]] = []
        for w in wallets:
            name = str(w.get("name", "Unnamed Wallet"))
            addrs = [str(a).strip() for a in w.get("addresses", []) if str(a).strip()]
            if addrs:
                result.append((name, addrs))
        if not result:
            raise SystemExit("No wallets/addresses found in config JSON")
        return result

    # Single wallet inputs
    agg: List[str] = []
    if addresses_csv:
        agg.extend([a.strip() for a in addresses_csv.split(",") if a.strip()])
    if file_path:
        for line in Path(file_path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            agg.append(line)
    if not agg:
        raise SystemExit("No addresses provided. Use --addresses/--file or --config.")
    return [(single_wallet_name, agg)]


def http_get_json(url: str, timeout: float) -> dict:
    req = Request(url, headers={"User-Agent": "btc-balance-scanner/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            data = resp.read().decode(charset)
            return json.loads(data)
    except HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} for {url}") from e
    except URLError as e:
        raise RuntimeError(f"Network error for {url}: {e}") from e


def fetch_address_balance(api_base: str, address: str, timeout: float) -> AddressBalance:
    info_url = urljoin(api_base, f"address/{address}")
    data = http_get_json(info_url, timeout=timeout)

    chain_stats = data.get("chain_stats", {})
    mempool_stats = data.get("mempool_stats", {})

    confirmed = int(chain_stats.get("funded_txo_sum", 0)) - int(chain_stats.get("spent_txo_sum", 0))
    mempool_delta = int(mempool_stats.get("funded_txo_sum", 0)) - int(mempool_stats.get("spent_txo_sum", 0))

    return AddressBalance(address=address, confirmed=confirmed, mempool_delta=mempool_delta)


def scan_wallet(
    api_base: str,
    wallet_name: str,
    addresses: Iterable[str],
    concurrency: int,
    rate_limit_ms: int,
    timeout: float,
) -> WalletScanResult:
    addresses_list = list(dict.fromkeys(a.strip() for a in addresses if a.strip()))  # de-dupe, preserve order
    results: List[Optional[AddressBalance]] = [None] * len(addresses_list)

    def worker(idx_and_addr: Tuple[int, str]) -> Tuple[int, AddressBalance]:
        idx, addr = idx_and_addr
        if rate_limit_ms:
            time.sleep(rate_limit_ms / 1000.0)
        bal = fetch_address_balance(api_base, addr, timeout=timeout)
        return idx, bal

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [executor.submit(worker, item) for item in enumerate(addresses_list)]
        for fut in concurrent.futures.as_completed(futures):
            idx, bal = fut.result()
            results[idx] = bal

    ordered_results: List[AddressBalance] = [r for r in results if r is not None]
    return WalletScanResult(name=wallet_name, addresses=ordered_results)


def format_sats(sats: int) -> str:
    sign = "-" if sats < 0 else ""
    sats_abs = abs(sats)
    btc = sats_abs / 100_000_000
    return f"{sign}{sats_abs:,} sats ({sign}{btc:.8f} BTC)"


def print_table(wallets: List[WalletScanResult], include_mempool: bool, show_addresses: bool) -> None:
    rows: List[List[str]] = []
    # headers
    if show_addresses:
        rows.append(["Wallet", "Address", "Confirmed", "Mempool Δ", "Total (incl. mempool)"])
    rows.append(["Wallet", "Confirmed", "Mempool Δ", "Total (incl. mempool)"])

    for w in wallets:
        if show_addresses:
            for a in w.addresses:
                rows.append([
                    w.name,
                    a.address,
                    format_sats(a.confirmed),
                    format_sats(a.mempool_delta),
                    format_sats(a.total_including_mempool),
                ])
        rows.append([
            w.name,
            format_sats(w.confirmed_total),
            format_sats(w.mempool_delta_total),
            format_sats(w.total_including_mempool),
        ])

    # compute column widths per column count; there are two possible row widths
    max_cols = max(len(r) for r in rows)
    col_widths = [0] * max_cols
    for r in rows:
        for i, cell in enumerate(r):
            col_widths[i] = max(col_widths[i], len(cell))

    def fmt_row(r: List[str]) -> str:
        return "  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(r))

    # Print
    printed_header_for_width: Dict[int, bool] = {}
    for r in rows:
        width = len(r)
        if width not in printed_header_for_width:
            # find the header row matching this width and print it with divider
            for maybe_header in rows:
                if len(maybe_header) == width and maybe_header[0] == "Wallet":
                    print(fmt_row(maybe_header))
                    print("  ".join("-" * col_widths[i] for i in range(width)))
                    printed_header_for_width[width] = True
                    break
        print(fmt_row(r))


def print_json(wallets: List[WalletScanResult]) -> None:
    obj = {
        "wallets": [
            {
                "name": w.name,
                "confirmed_sats": w.confirmed_total,
                "mempool_delta_sats": w.mempool_delta_total,
                "total_incl_mempool_sats": w.total_including_mempool,
                "addresses": [asdict(a) for a in w.addresses],
            }
            for w in wallets
        ]
    }
    print(json.dumps(obj, indent=2))


def print_csv(wallets: List[WalletScanResult]) -> None:
    writer = csv.writer(sys.stdout)
    writer.writerow(["wallet", "address", "confirmed_sats", "mempool_delta_sats", "total_incl_mempool_sats"])
    for w in wallets:
        for a in w.addresses:
            writer.writerow([
                w.name,
                a.address,
                a.confirmed,
                a.mempool_delta,
                a.total_including_mempool,
            ])
        # summary row per wallet (address column blank)
        writer.writerow([
            w.name,
            "",
            w.confirmed_total,
            w.mempool_delta_total,
            w.total_including_mempool,
        ])


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    api_base = resolve_api_base(args.network, args.api_base)

    wallet_inputs = load_inputs(args.addresses, args.file, args.config, args.wallet_name)

    wallets: List[WalletScanResult] = []
    for wallet_name, addresses in wallet_inputs:
        result = scan_wallet(
            api_base=api_base,
            wallet_name=wallet_name,
            addresses=addresses,
            concurrency=args.concurrency,
            rate_limit_ms=args.rate_limit_ms,
            timeout=args.timeout,
        )
        wallets.append(result)

    # Output
    if args.format == "json":
        print_json(wallets)
    elif args.format == "csv":
        print_csv(wallets)
    else:
        print_table(wallets, include_mempool=args.include_mempool, show_addresses=args.show_addresses)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
