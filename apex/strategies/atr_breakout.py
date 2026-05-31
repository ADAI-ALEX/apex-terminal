"""ATR Breakout — trades expansion out of compression.

After ``breakout_compression_candles`` of below-percentile ATR (a coiled spring),
a close beyond the recent range triggers a breakout in that direction. Highest
reward:risk of the three. Authority: ALL regimes.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.config import Direction, Market
from apex.indicators.engine import atr_series
from apex.models import Candle, IndicatorSnapshot, Signal
from apex.strategies.base import Strategy


class AtrBreakoutStrategy(Strategy):
    name = "atr_breakout"
    authority = None  # all regimes

    def evaluate(
        self, market: Market, snapshot: IndicatorSnapshot, candles: Sequence[Candle]
    ) -> Signal | None:
        s = snapshot
        lookback = max(self.p.atr_period * 2, 30)
        if s.atr is None or len(candles) < lookback + self.p.breakout_compression_candles:
            return None

        atrs = atr_series(candles, self.p.atr_period)
        if len(atrs) < self.p.breakout_compression_candles + 5:
            return None

        # Was the market compressed over the last N candles?
        recent = atrs[-self.p.breakout_compression_candles:]
        threshold = _percentile(atrs, self.p.breakout_compression_pctile)
        compressed = all(a <= threshold for a in recent[:-1])
        if not compressed:
            return None

        # Range of the compression window (exclude the breakout candle itself).
        window = candles[-(self.p.breakout_compression_candles + 1):-1]
        if not window:
            return None
        range_high = max(c.high for c in window)
        range_low = min(c.low for c in window)

        if s.price > range_high:
            return self._build_signal(
                market, s, Direction.BUY, self.p.breakout_target_rr,
                confidence=0.55,
                rationale=f"Breakout above {range_high:.1f} after {self.p.breakout_compression_candles} compressed candles",
            )
        if s.price < range_low:
            return self._build_signal(
                market, s, Direction.SELL, self.p.breakout_target_rr,
                confidence=0.55,
                rationale=f"Breakdown below {range_low:.1f} after {self.p.breakout_compression_candles} compressed candles",
            )
        return None


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (pct in 0..1)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac
