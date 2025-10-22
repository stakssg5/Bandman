from __future__ import annotations

import json
import urllib.request
import urllib.parse
from dataclasses import dataclass
from typing import Optional

from .config import get_chain_registry


@dataclass
class BalanceResult:
    chain: str  # chain key, e.g., "eth", "btc"
    address: str
    raw_balance: str  # hex for EVM; satoshi or units otherwise
    display: str      # human-readable string


def _http_json(url: str, data: Optional[dict] = None, headers: Optional[dict] = None, timeout: float = 10.0):
    payload: Optional[bytes] = None
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload)
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# -------- EVM (ETH-like) JSON-RPC --------

def evm_get_balance(chain_key: str, rpc_url: str, address: str) -> BalanceResult:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBalance",
        "params": [address, "latest"],
    }
    data = _http_json(rpc_url, data=payload)
    raw_hex = data.get("result", "0x0")
    try:
        wei = int(raw_hex, 16)
    except ValueError:
        wei = 0
    ether = wei / 10**18
    return BalanceResult(chain=chain_key, address=address, raw_balance=raw_hex, display=f"{ether:.8f}")


# -------- Bitcoin (Blockstream REST) --------

def btc_get_balance(chain_key: str, api_base: str, address: str) -> BalanceResult:
    # We compute total funded - spent from addr data
    u = f"{api_base}/address/{urllib.parse.quote(address)}"
    with urllib.request.urlopen(u, timeout=10.0) as resp:
        info = json.loads(resp.read().decode("utf-8"))
    funded = info.get("chain_stats", {}).get("funded_txo_sum", 0) + info.get("mempool_stats", {}).get("funded_txo_sum", 0)
    spent = info.get("chain_stats", {}).get("spent_txo_sum", 0) + info.get("mempool_stats", {}).get("spent_txo_sum", 0)
    sats = int(funded) - int(spent)
    btc = sats / 10**8
    return BalanceResult(chain=chain_key, address=address, raw_balance=str(sats), display=f"{btc:.8f}")


# -------- Tron (TronGrid) --------

def tron_get_balance(chain_key: str, api_base: str, address: str) -> BalanceResult:
    u = f"{api_base}/v1/accounts/{urllib.parse.quote(address)}"
    try:
        with urllib.request.urlopen(u, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        data = {}
    balance = 0
    if isinstance(data, dict):
        try:
            # naive scan for TRX balance in data
            data_list = data.get("data", [])
            if data_list:
                balance = int(data_list[0].get("balance", 0))
        except Exception:
            balance = 0
    trx = balance / 10**6
    return BalanceResult(chain=chain_key, address=address, raw_balance=str(balance), display=f"{trx:.6f}")


def get_checker_for_chain(chain_key: str):
    reg = get_chain_registry()
    ch = reg.get(chain_key)
    if not ch:
        raise KeyError(f"Unknown chain: {chain_key}")
    if chain_key in ("eth", "polygon", "bsc", "op"):
        return lambda addr: evm_get_balance(chain_key, ch.rpc_url_factory(), addr)
    if chain_key == "btc":
        return lambda addr: btc_get_balance(chain_key, ch.rpc_url_factory(), addr)
    if chain_key == "tron":
        return lambda addr: tron_get_balance(chain_key, ch.rpc_url_factory(), addr)
    raise KeyError(f"No checker implemented for: {chain_key}")
