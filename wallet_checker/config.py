from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional


@dataclass(frozen=True)
class Chain:
    key: str
    name: str
    ticker: str
    # Callable that returns a JSON-RPC endpoint URL. Could rotate or read env.
    rpc_url_factory: Callable[[], str]


def _env_or_default(env_key: str, default: str) -> str:
    import os

    return os.getenv(env_key, default)


def get_chain_registry() -> Dict[str, Chain]:
    """Return a mapping of chain key -> Chain metadata.

    RPC URLs default to public/shared endpoints suitable for demos and will
    likely be rate-limited. Users can override via environment variables.
    """

    return {
        # Ethereum (EVM JSON-RPC)
        "eth": Chain(
            key="eth",
            name="Ethereum",
            ticker="ETH",
            rpc_url_factory=lambda: _env_or_default(
                "ETH_RPC_URL", "https://cloudflare-eth.com"
            ),
        ),
        # Polygon (EVM JSON-RPC)
        "polygon": Chain(
            key="polygon",
            name="Polygon",
            ticker="MATIC",
            rpc_url_factory=lambda: _env_or_default(
                "POLYGON_RPC_URL", "https://polygon-rpc.com"
            ),
        ),
        # BSC (EVM JSON-RPC)
        "bsc": Chain(
            key="bsc",
            name="BNB Smart Chain",
            ticker="BNB",
            rpc_url_factory=lambda: _env_or_default(
                "BSC_RPC_URL", "https://bsc-dataseed.binance.org"
            ),
        ),
        # Optimism (EVM JSON-RPC)
        "op": Chain(
            key="op",
            name="Optimism",
            ticker="OP",
            rpc_url_factory=lambda: _env_or_default(
                "OP_RPC_URL", "https://mainnet.optimism.io"
            ),
        ),
        # Bitcoin (REST via Blockstream for demo)
        "btc": Chain(
            key="btc",
            name="Bitcoin",
            ticker="BTC",
            rpc_url_factory=lambda: _env_or_default(
                "BTC_API_BASE", "https://blockstream.info/api"
            ),
        ),
        # Tron (HTTP API)
        "tron": Chain(
            key="tron",
            name="Tron",
            ticker="TRX",
            rpc_url_factory=lambda: _env_or_default(
                "TRON_API_BASE", "https://api.trongrid.io"
            ),
        ),
    }
