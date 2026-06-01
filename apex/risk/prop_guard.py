"""PropGuard — the prop-firm floating-equity circuit breaker (Step 4).

Where :class:`~apex.risk.risk_engine.RiskEngine` gates *entries*, PropGuard guards
*the account* in real time. It is sampled every ``equity_poll_seconds`` (1s) by the
heartbeat with the current **floating** equity and decides one of:

* ``OK``        — within limits.
* ``WARN``      — approaching a limit; surfaced to the dashboard.
* ``LIQUIDATE`` — within ``circuit_buffer_pct`` of a hard limit. The heartbeat must
  immediately flatten every position, cancel working orders, and lock trading until
  the next daily reset (daily breach) or a manual restart (total breach).

It tracks two drawdowns the way a prop auditor does:

* **Daily** — from the equity captured at the prop daily-reset time
  (``daily_reset_hour`` in ``daily_reset_tz``; default 17:00 New York).
* **Total** — from the all-time **high-water peak** equity.

The class is deliberately broker-free: feed it equity + time, act on the decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from loguru import logger

from apex.config import PropFirmParams

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


class PropAction(str, Enum):
    OK = "OK"
    WARN = "WARN"
    LIQUIDATE = "LIQUIDATE"


@dataclass
class PropDecision:
    action: PropAction
    daily_dd_pct: float          # current daily drawdown, positive %
    total_dd_pct: float          # current drawdown from peak, positive %
    locked: bool                 # are new entries / holds disallowed right now?
    reason: str = ""


class PropGuard:
    def __init__(self, params: PropFirmParams) -> None:
        self.p = params
        self._day_anchor: datetime | None = None    # start-of-trading-day timestamp (UTC)
        self._day_start_equity: float | None = None
        self._peak_equity: float | None = None
        self._daily_locked = False
        self._total_locked = False

    # ── public API ────────────────────────────────────────────────────
    @property
    def locked(self) -> bool:
        return self._daily_locked or self._total_locked

    def evaluate(self, equity: float, now: datetime | None = None) -> PropDecision:
        """Update state from a new equity sample and return the guard decision."""
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        equity = max(float(equity), 0.0)

        self._roll_day(now, equity)

        if self._day_start_equity is None:
            self._day_start_equity = equity
        if self._peak_equity is None or equity > self._peak_equity:
            self._peak_equity = equity

        daily_dd = self._pct_drop(self._day_start_equity, equity)
        total_dd = self._pct_drop(self._peak_equity, equity)

        if not self.p.enabled:
            return PropDecision(PropAction.OK, daily_dd, total_dd, locked=False,
                                reason="Prop guard disabled (non-prop profile).")

        daily_trigger = self.p.daily_dd_limit_pct - self.p.circuit_buffer_pct
        total_trigger = self.p.total_dd_limit_pct - self.p.circuit_buffer_pct

        # ── Hard liquidation triggers ─────────────────────────────────
        if total_dd >= total_trigger:
            if not self._total_locked:
                logger.error("PROP CIRCUIT BREAKER (TOTAL): {:.2f}% >= {:.2f}% — LIQUIDATE + LOCK (manual restart).",
                             total_dd, total_trigger)
            self._total_locked = True
            return PropDecision(PropAction.LIQUIDATE, daily_dd, total_dd, locked=True,
                                reason=f"Total drawdown {total_dd:.2f}% within {self.p.circuit_buffer_pct}% "
                                       f"of the {self.p.total_dd_limit_pct}% limit.")

        if daily_dd >= daily_trigger:
            if not self._daily_locked:
                logger.error("PROP CIRCUIT BREAKER (DAILY): {:.2f}% >= {:.2f}% — LIQUIDATE + LOCK until reset.",
                             daily_dd, daily_trigger)
            self._daily_locked = True
            return PropDecision(PropAction.LIQUIDATE, daily_dd, total_dd, locked=True,
                                reason=f"Daily drawdown {daily_dd:.2f}% within {self.p.circuit_buffer_pct}% "
                                       f"of the {self.p.daily_dd_limit_pct}% limit.")

        # Still locked from an earlier trip this period.
        if self.locked:
            return PropDecision(PropAction.LIQUIDATE, daily_dd, total_dd, locked=True,
                                reason="Locked after an earlier circuit-breaker trip.")

        # ── Soft warning band (70% of the way to the trigger) ─────────
        if daily_dd >= 0.7 * daily_trigger or total_dd >= 0.7 * total_trigger:
            return PropDecision(PropAction.WARN, daily_dd, total_dd, locked=False,
                                reason=f"Approaching limit — daily {daily_dd:.2f}%, total {total_dd:.2f}%.")

        return PropDecision(PropAction.OK, daily_dd, total_dd, locked=False)

    def manual_reset(self) -> None:
        """Clear a latched TOTAL-drawdown lock (operator action after review)."""
        self._total_locked = False
        logger.warning("PropGuard total-drawdown lock manually cleared.")

    # ── internals ─────────────────────────────────────────────────────
    def _roll_day(self, now_utc: datetime, equity: float) -> None:
        """Reset the daily baseline (and daily lock) when a new prop day begins."""
        anchor = self._current_day_anchor(now_utc)
        if self._day_anchor is None or anchor > self._day_anchor:
            self._day_anchor = anchor
            self._day_start_equity = equity
            if self._daily_locked:
                logger.info("New prop trading day — daily circuit breaker reset.")
            self._daily_locked = False

    def _current_day_anchor(self, now_utc: datetime) -> datetime:
        """Most recent reset-hour boundary at/just before ``now`` (returned in UTC)."""
        tz = self._tz()
        local = now_utc.astimezone(tz)
        boundary = local.replace(hour=self.p.daily_reset_hour, minute=0, second=0, microsecond=0)
        if local < boundary:
            # Before today's reset → the active day started at yesterday's reset.
            from datetime import timedelta

            boundary = boundary - timedelta(days=1)
        return boundary.astimezone(timezone.utc)

    def _tz(self):  # type: ignore[no-untyped-def]
        if ZoneInfo is not None:
            try:
                return ZoneInfo(self.p.daily_reset_tz)
            except Exception:  # pragma: no cover
                pass
        return timezone.utc

    @staticmethod
    def _pct_drop(reference: float | None, equity: float) -> float:
        if not reference or reference <= 0:
            return 0.0
        return max(0.0, 100.0 * (reference - equity) / reference)
