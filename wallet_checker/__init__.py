"""Wallet checker core modules.

Provides chain checkers, address queue, and rate limiting utilities
that can be embedded into GUI or CLI frontends.
"""

from .config import get_chain_registry  # re-export for convenience

__all__ = ["get_chain_registry"]
