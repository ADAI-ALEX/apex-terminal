"""PropGuard tests — the prop-firm floating-equity circuit breaker."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apex.config import PropFirmParams
from apex.risk.prop_guard import PropAction, PropGuard


def _params() -> PropFirmParams:
    # Reset at 00:00 UTC keeps the day-rollover maths trivial to assert.
    return PropFirmParams(
        enabled=True,
        daily_dd_limit_pct=3.0,
        total_dd_limit_pct=8.0,
        circuit_buffer_pct=0.5,
        daily_reset_hour=0,
        daily_reset_tz="UTC",
    )


_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_baseline_then_ok():
    g = PropGuard(_params())
    d = g.evaluate(100_000, _T0)
    assert d.action is PropAction.OK
    assert d.daily_dd_pct == 0.0 and d.total_dd_pct == 0.0


def test_warns_before_trigger():
    g = PropGuard(_params())
    g.evaluate(100_000, _T0)
    d = g.evaluate(98_000, _T0)  # −2.0% daily; trigger is 2.5%
    assert d.action is PropAction.WARN
    assert round(d.daily_dd_pct, 2) == 2.0
    assert not d.locked


def test_daily_breaker_liquidates_and_locks():
    g = PropGuard(_params())
    g.evaluate(100_000, _T0)
    d = g.evaluate(97_500, _T0)  # −2.5% == limit(3) − buffer(0.5)
    assert d.action is PropAction.LIQUIDATE
    assert d.locked
    # Stays locked even if equity recovers within the same day.
    again = g.evaluate(99_500, _T0)
    assert again.action is PropAction.LIQUIDATE and again.locked


def test_daily_lock_clears_on_new_day():
    g = PropGuard(_params())
    g.evaluate(100_000, _T0)
    g.evaluate(97_500, _T0)            # trip daily
    nxt = g.evaluate(99_000, _T0 + timedelta(days=1))  # next UTC day
    assert nxt.action is PropAction.OK
    assert not nxt.locked


def test_total_breaker_needs_manual_reset():
    g = PropGuard(_params())
    g.evaluate(100_000, _T0)
    d = g.evaluate(92_500, _T0)        # −7.5% from peak == 8 − 0.5
    assert d.action is PropAction.LIQUIDATE and d.locked
    # A new day does NOT clear a total-drawdown lock.
    nxt = g.evaluate(95_000, _T0 + timedelta(days=2))
    assert nxt.locked
    g.manual_reset()
    cleared = g.evaluate(95_000, _T0 + timedelta(days=2))
    assert not cleared.locked


def test_disabled_guard_never_locks():
    g = PropGuard(PropFirmParams(enabled=False))
    g.evaluate(100_000, _T0)
    d = g.evaluate(80_000, _T0)        # −20% but guard disabled
    assert d.action is PropAction.OK and not d.locked
