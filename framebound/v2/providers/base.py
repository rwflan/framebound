"""Capability discovery + bounded transient retry. No fabricated output, ever.

Capability states (explicit, never a bare key-presence boolean):
- not_configured: no MODEL_API_KEY/META_API_KEY in the environment.
- unverified: a key exists but no live probe has succeeded yet.
- verified: a live probe succeeded (transport recorded, timestamped).
- permission_denied / model_unavailable / transport_error / response_invalid:
  terminal probe outcomes mapped from HTTP/parse failures.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass

DEFAULT_BASE = "https://api.meta.ai/v1"


@dataclass(frozen=True)
class Capability:
    name: str
    supported: bool
    reason: str  # not_configured | unverified | verified | permission_denied | ...


def _key() -> str:
    return os.environ.get("MODEL_API_KEY") or os.environ.get("META_API_KEY") or ""


def _base() -> str:
    return (os.environ.get("META_BASE_URL") or DEFAULT_BASE).rstrip("/")


def model_for(capability: str) -> str:
    if capability in ("image", "image-generation"):
        return os.environ.get("FRAMEBOUND_IMAGE_MODEL") or "muse-image-1.0"
    if capability in ("spark", "critique"):
        return os.environ.get("FRAMEBOUND_VISION_MODEL") or "muse-spark-1.3"
    if capability in ("sam", "segmentation"):
        return os.environ.get("FRAMEBOUND_SAM_MODEL") or "sam-3.1"
    return os.environ.get("FRAMEBOUND_MODEL") or "muse-spark-1.3"


def discover(provider: str) -> Capability:
    """Offline-safe discovery: key presence alone never reports verified support."""
    if not _key():
        return Capability(provider, False, "not_configured: set MODEL_API_KEY to enable live calls")
    return Capability(provider, False,
                      "unverified: key present but no live probe has succeeded; "
                      "call verify_capability before treating the provider as available")


def verify_capability(provider: str, *, transport=None, timeout: float = 30.0) -> Capability:
    """Minimal live probe mapping transport outcomes to explicit states."""
    from ..services import errors as E
    if not _key():
        return Capability(provider, False, "not_configured: set MODEL_API_KEY to enable live calls")
    model = model_for(provider)
    sender = transport or _default_sender
    try:
        sender(provider, model, {"model": model, "input": "ok", "max_tokens": 1},
               timeout=timeout)
    except E.PermissionDenied as e:
        return Capability(provider, False, f"permission_denied: {e}")
    except E.ModelUnavailable as e:
        return Capability(provider, False, f"model_unavailable: {e}")
    except (E.RateLimited, E.ProviderTimeout, E.TransportError,
            TimeoutError, ConnectionError) as e:
        return Capability(provider, False, f"transport_error: {e}")
    except E.ResponseInvalid as e:
        return Capability(provider, False, f"response_invalid: {e}")
    except Exception as e:  # never let a probe raise past the caller
        return Capability(provider, False, f"transport_error: {type(e).__name__}: {e}")
    return Capability(provider, True, f"verified: {provider}/{model} probe succeeded")


def _default_sender(provider: str, model: str, payload: dict, *, timeout: float):
    return http_post("/responses", payload, timeout=timeout,
                     idempotency_key=f"probe-{provider}")


def http_post(path: str, payload: dict, *, timeout: float = 120.0,
              idempotency_key: str | None = None,
              transport=None, permit=None) -> dict:
    """POST JSON to the Meta Model API with structured error mapping.

    `transport` is an injectable callable (http_request -> response dict) used
    by contract tests to simulate 401/404/429/5xx/timeout outcomes.
    """
    from ..services import errors as E
    if permit is not None:
        from ..services.provider_grants import DispatchPermit
        if type(permit) is not DispatchPermit:raise E.InvalidInput('invalid dispatch permit type')
        DispatchPermit.consume(permit,payload,simulated=transport is not None)
    elif transport is None:
        from ..services.errors import InvalidInput
        raise InvalidInput('live provider I/O requires a durable dispatch permit')
    return _http_post_approved(path,payload,timeout=timeout,idempotency_key=idempotency_key,
                               transport=transport,endpoint=permit.endpoint if permit is not None else _base())


def _http_post_approved(path, payload, *, timeout=120.0, idempotency_key=None,
                        transport=None, endpoint=DEFAULT_BASE):
    """Wire/error mapping only; the public caller consumes authorization first."""
    from ..services import errors as E
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {_key()}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if transport is not None:
        try:
            resp = transport({"path": path, "headers": headers, "body": payload,
                              "timeout": timeout})
        except (E.RateLimited, E.ProviderTimeout, E.PermissionDenied,
                E.ModelUnavailable, E.ResponseInvalid, E.TransportError):
            raise
        except (TimeoutError, ConnectionError) as e:
            raise E.TransportError(f"transport_error: {e}") from e
        return resp
    req = urllib.request.Request(endpoint + path, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:500]
        except Exception:
            detail = ""
        if e.code in (401, 403):
            raise E.PermissionDenied(f"permission_denied: HTTP {e.code} {detail}") from e
        if e.code == 404 or (e.code == 400 and "model" in detail.lower()):
            raise E.ModelUnavailable(f"model_unavailable: HTTP {e.code} {detail}") from e
        if e.code == 429:
            raise E.RateLimited(f"rate_limited: HTTP 429 {detail}") from e
        if 500 <= e.code < 600:
            raise E.TransportError(f"transport_error: HTTP {e.code} {detail}") from e
        raise E.ResponseInvalid(f"response_invalid: HTTP {e.code} {detail}") from e
    except urllib.error.URLError as e:
        raise E.TransportError(f"transport_error: {e}") from e
    except (TimeoutError, ConnectionError) as e:
        raise E.ProviderTimeout(f"provider_timeout: {e}") from e
    try:
        return json.loads(raw)
    except Exception as e:
        raise E.ResponseInvalid(f"response_invalid: response is not JSON: {e}") from e


def retry_transient(fn, *, attempts: int = 3, base_seconds: float = 1.0):
    """Retry only bounded transient failures with backoff. Returns (result, tries)."""
    from ..services.errors import RateLimited, ProviderTimeout, TransportError
    last = None
    for i in range(1, attempts + 1):
        try:
            return fn(), i
        except (RateLimited, ProviderTimeout, TransportError, TimeoutError,
                ConnectionError) as e:
            last = e
            time.sleep(base_seconds * (2 ** (i - 1)))
    raise last
