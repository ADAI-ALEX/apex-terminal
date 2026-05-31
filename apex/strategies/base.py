"""Strategy base class and shared helpers.

A strategy is a pure function of (snapshot, candles) → Optional[Signal]. It never
touches the broker, account, or risk state — that separation is what lets the
risk engine and Claude sit cleanly in between signal and execution.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from apex.config import Direction, Market, Regime, StrategyParams, get_settings
from apex.models import Candle, IndicatorSnapshot, Signal


class Strategy(ABC):
    """Base class. Subclasses set ``name`` and ``authority`` and implement ``evaluate``."""

    name: str = "base"
    #: Regimes in which this strategy is allowed to fire (None => all regimes).
    authority: tuple[Regime, ...] | None = None

    def __init__(self, params: StrategyParams | None = None) -> None:
        self.p = params or get_settings().strategy

    def has_authority(self, regime: Regime | None) -> bool:
        if self.authority is None or regime is None:
            return True
        return regime in self.authority

    @abstractmethod
    def evaluate(
        self, market: Market, snapshot: IndicatorSnapshot, candles: Sequence[Candle]
    ) -> Signal | None:
        """Return a Signal if the entry conditions are met, else None."""
        raise NotImplementedError

    # ── shared helpers ────────────────────────────────────────────────
    def _build_signal(
        self,
        market: Market,
        snapshot: IndicatorSnapshot,
        direction: Direction,
        target_rr: float,
        confidence: float,
        rationale: str,
    ) -> Signal | None:
        """Construct a Signal with an ATR-derived stop and an RR-derived target.

        Returns None if ATR isn't ready (we never trade without a measurable stop).
        """
        if snapshot.atr is None or snapshot.atr <= 0:
            return None
        entry = snapshot.price
        stop_dist = snapshot.atr * get_settings().risk.atr_stop_multiplier
        stop_dist = max(stop_dist, market.min_stop_points)
        target_dist = stop_dist * target_rr

        if direction is Direction.BUY:
            stop = entry - stop_dist
            target = entry + target_dist
        else:
            stop = entry + stop_dist
            target = entry - target_dist

        return Signal(
            market_key=market.key,
            epic=market.epic,
            strategy=self.name,
            direction=direction,
            entry=entry,
            stop=round(stop, 2),
            target=round(target, 2),
            target_rr=target_rr,
            confidence=confidence,
            rationale=rationale,
            regime=snapshot.regime,
        )
