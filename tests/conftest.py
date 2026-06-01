"""Shared test fixtures / builders."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import pytest

from apex.models import Candle


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """Point the onboarding store at an empty temp dir so tests stay hermetic.

    Without this, a real ``~/.apex/runtime.json.enc`` on the dev machine would
    overlay onto Settings and change risk defaults under the tests' feet.
    """
    monkeypatch.setenv("APEX_CONFIG_DIR", str(tmp_path / "apex_cfg"))
    from apex.config import reload_settings

    reload_settings()
    yield
    reload_settings()


def make_candles(closes: Sequence[float], spread: float = 0.5) -> list[Candle]:
    """Build a candle series from a list of closes (synthetic OHLC around close)."""
    out: list[Candle] = []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    prev = closes[0]
    for i, c in enumerate(closes):
        hi = max(prev, c) + spread
        lo = min(prev, c) - spread
        out.append(Candle(time=base + timedelta(minutes=5 * i), open=prev,
                          high=hi, low=lo, close=c, volume=100))
        prev = c
    return out
