"""Capability discovery + bounded transient retry. No fabricated output, ever."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    name: str
    supported: bool
    reason: str  # "live" | "not_configured" | "unsupported" | failure detail


def _key() -> str:
    return os.environ.get("MODEL_API_KEY") or os.environ.get("META_API_KEY") or ""


def discover(provider: str) -> Capability:
    """Without credentials: not_configured. Offline procedural + recorded replay stay distinct."""
    if not _key():
        return Capability(provider, False, "not_configured: set MODEL_API_KEY to enable live calls")
    return Capability(provider, True, "live: key present (verify endpoints with a redacted spike)")


def retry_transient(fn, *, attempts: int = 3, base_seconds: float = 1.0):
    """Retry only bounded transient failures with backoff. Returns (result, tries)."""
    from ..services.errors import RateLimited, ProviderTimeout
    last = None
    for i in range(1, attempts + 1):
        try:
            return fn(), i
        except (RateLimited, ProviderTimeout, TimeoutError, ConnectionError) as e:
            last = e
            time.sleep(base_seconds * (2 ** (i - 1)))
    raise last
