"""Pure-Python technical indicators.

Deliberately dependency-free (no numpy/pandas at import time): the data volumes
here are tiny (a few hundred candles per instrument) and a pure implementation is
fast enough, trivially unit-testable, and import-safe on any machine.

All functions accept plain lists of floats / :class:`~apex.models.Candle` and
return either a single latest value or a full series. Where there is insufficient
data, ``None`` is returned rather than raising — callers treat ``None`` as
"indicator not ready yet".
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.config import StrategyParams, get_settings
from apex.models import Candle, IndicatorSnapshot


# ──────────────────────────────────────────────────────────────────────────
#  Moving averages
# ──────────────────────────────────────────────────────────────────────────
def sma(values: Sequence[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def ema_series(values: Sequence[float], period: int) -> list[float]:
    """Full EMA series. Seeded with the SMA of the first ``period`` values."""
    if len(values) < period or period <= 0:
        return []
    k = 2.0 / (period + 1.0)
    seed = sum(values[:period]) / period
    out = [seed]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def ema(values: Sequence[float], period: int) -> float | None:
    series = ema_series(values, period)
    return series[-1] if series else None


# ──────────────────────────────────────────────────────────────────────────
#  RSI (Wilder's smoothing)
# ──────────────────────────────────────────────────────────────────────────
def rsi(values: Sequence[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(delta, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-delta, 0.0)) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ──────────────────────────────────────────────────────────────────────────
#  MACD
# ──────────────────────────────────────────────────────────────────────────
def macd(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[float, float, float] | None:
    """Return (macd_line, signal_line, histogram) or None if not enough data."""
    if len(values) < slow + signal:
        return None
    fast_series = ema_series(values, fast)
    slow_series = ema_series(values, slow)
    # Align tails (slow series is shorter).
    n = min(len(fast_series), len(slow_series))
    if n == 0:
        return None
    macd_line = [fast_series[-n + i] - slow_series[-n + i] for i in range(n)]
    sig_series = ema_series(macd_line, signal)
    if not sig_series:
        return None
    macd_v = macd_line[-1]
    signal_v = sig_series[-1]
    return macd_v, signal_v, macd_v - signal_v


# ──────────────────────────────────────────────────────────────────────────
#  ATR (Wilder)
# ──────────────────────────────────────────────────────────────────────────
def _true_ranges(candles: Sequence[Candle]) -> list[float]:
    trs: list[float] = []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        trs.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))
    return trs


def atr_series(candles: Sequence[Candle], period: int = 14) -> list[float]:
    trs = _true_ranges(candles)
    if len(trs) < period:
        return []
    out = [sum(trs[:period]) / period]
    for tr in trs[period:]:
        out.append((out[-1] * (period - 1) + tr) / period)
    return out


def atr(candles: Sequence[Candle], period: int = 14) -> float | None:
    series = atr_series(candles, period)
    return series[-1] if series else None


# ──────────────────────────────────────────────────────────────────────────
#  Bollinger Bands
# ──────────────────────────────────────────────────────────────────────────
def bollinger(
    values: Sequence[float], period: int = 20, num_std: float = 2.0
) -> tuple[float, float, float] | None:
    """Return (upper, mid, lower) or None."""
    if len(values) < period:
        return None
    window = values[-period:]
    mid = sum(window) / period
    variance = sum((v - mid) ** 2 for v in window) / period
    std = variance**0.5
    return mid + num_std * std, mid, mid - num_std * std


# ──────────────────────────────────────────────────────────────────────────
#  ADX (directional movement) — Wilder
# ──────────────────────────────────────────────────────────────────────────
def adx(candles: Sequence[Candle], period: int = 14) -> float | None:
    if len(candles) < 2 * period + 1:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        up = c.high - p.high
        down = p.low - c.low
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        trs.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))

    def _wilder_smooth(seq: list[float]) -> list[float]:
        smoothed = [sum(seq[:period])]
        for v in seq[period:]:
            smoothed.append(smoothed[-1] - smoothed[-1] / period + v)
        return smoothed

    sm_tr = _wilder_smooth(trs)
    sm_plus = _wilder_smooth(plus_dm)
    sm_minus = _wilder_smooth(minus_dm)

    dx_values: list[float] = []
    for tr_v, p_v, m_v in zip(sm_tr, sm_plus, sm_minus, strict=False):
        if tr_v == 0:
            continue
        di_plus = 100.0 * p_v / tr_v
        di_minus = 100.0 * m_v / tr_v
        denom = di_plus + di_minus
        if denom == 0:
            dx_values.append(0.0)
        else:
            dx_values.append(100.0 * abs(di_plus - di_minus) / denom)

    if len(dx_values) < period:
        return None
    return sum(dx_values[-period:]) / period


# ──────────────────────────────────────────────────────────────────────────
#  Snapshot builder
# ──────────────────────────────────────────────────────────────────────────
def build_snapshot(
    market_key: str,
    epic: str,
    candles: Sequence[Candle],
    params: StrategyParams | None = None,
) -> IndicatorSnapshot:
    """Compute every indicator from a candle history into one snapshot."""
    p = params or get_settings().strategy
    closes = [c.close for c in candles]
    price = closes[-1] if closes else 0.0

    macd_tuple = macd(closes, p.macd_fast, p.macd_slow, p.macd_signal)
    bb = bollinger(closes, p.bollinger_period, p.bollinger_std)
    atr_vals = atr_series(candles, p.atr_period)

    return IndicatorSnapshot(
        epic=epic,
        market_key=market_key,
        price=price,
        ema_fast=ema(closes, p.ema_fast),
        ema_mid=ema(closes, p.ema_mid),
        ema_slow=ema(closes, p.ema_slow),
        rsi=rsi(closes, p.rsi_period),
        macd=macd_tuple[0] if macd_tuple else None,
        macd_signal=macd_tuple[1] if macd_tuple else None,
        macd_hist=macd_tuple[2] if macd_tuple else None,
        atr=atr_vals[-1] if atr_vals else None,
        atr_prev=atr_vals[-2] if len(atr_vals) >= 2 else None,
        bb_upper=bb[0] if bb else None,
        bb_mid=bb[1] if bb else None,
        bb_lower=bb[2] if bb else None,
        adx=adx(candles, p.adx_period),
    )
