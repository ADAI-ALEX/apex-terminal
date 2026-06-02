"""Minimal Upstash/Vercel-KV REST client (no extra dependency — uses ``requests``).

Vercel KV is Upstash Redis under the hood and exposes a REST API. We read the same
env vars Vercel injects (``KV_REST_API_URL`` / ``KV_REST_API_TOKEN``) or the native
Upstash names. Values are stored as JSON strings, compatible with the dashboard's
``@vercel/kv`` client (which JSON-stringifies on set and parses on get).

Every call is best-effort and never raises: on any error it logs and returns a safe
default, so a KV blip can never crash the trading loop.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests
from loguru import logger

CONFIG_KEY = "apex:config"            # onboarding config written by the dashboard
STATE_KEY = "apex:state"              # live snapshot pushed by the laptop
STATUS_KEY = "apex:onboarding_status" # algo-confirmed onboarding status
BACKTEST_REQ_KEY = "apex:backtest_request"   # dashboard → laptop: run this backtest
BACKTEST_RES_KEY = "apex:backtest_result"    # laptop → dashboard: backtest result

_TIMEOUT = 8


def _creds() -> tuple[str | None, str | None]:
    url = os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL")
    token = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if url and token:
        return url.rstrip("/"), token
    return None, None


def kv_enabled() -> bool:
    """True when KV credentials are present (cloud-relay mode is active)."""
    url, token = _creds()
    return bool(url and token)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def kv_get(key: str) -> Any | None:
    """Return the JSON-decoded value at ``key``, or ``None`` if absent/unreachable."""
    url, token = _creds()
    if not url or not token:
        return None
    try:
        resp = requests.get(f"{url}/get/{key}", headers=_headers(token), timeout=_TIMEOUT)
        resp.raise_for_status()
        result = resp.json().get("result")
        if result in (None, ""):
            return None
        return json.loads(result) if isinstance(result, str) else result
    except Exception as exc:
        logger.warning("KV get '{}' failed: {}", key, exc)
        return None


def kv_set(key: str, value: Any) -> bool:
    """Store ``value`` (JSON-encoded) at ``key``. Returns success."""
    url, token = _creds()
    if not url or not token:
        return False
    try:
        body = json.dumps(value)
        resp = requests.post(f"{url}/set/{key}", headers=_headers(token), data=body, timeout=_TIMEOUT)
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("KV set '{}' failed: {}", key, exc)
        return False


def kv_delete(key: str) -> bool:
    url, token = _creds()
    if not url or not token:
        return False
    try:
        resp = requests.post(f"{url}/del/{key}", headers=_headers(token), timeout=_TIMEOUT)
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("KV del '{}' failed: {}", key, exc)
        return False
