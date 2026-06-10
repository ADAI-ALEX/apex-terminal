"""Sandboxed evaluator for user-authored custom strategies.

A custom strategy is a small Python snippet (written in the web code editor,
stored under ``apex/strategies/custom/``) that runs **once per bar** against the
local historical data array. It reads the cheat-sheet variables/functions and
sets ``signal`` to ``"BUY"``, ``"SELL"``, ``"FLAT"`` (or ``"HOLD"``/``None`` to do
nothing). The backtest engine turns that decision into ATR-sized entries/exits.

The snippet runs with a **restricted builtins** namespace and a static source
check that blocks imports, dunder access and filesystem/eval escapes — enough to
stop accidental or obvious-malicious code on a single-user local app. Any error
inside the snippet is swallowed and treated as ``HOLD`` so a typo can never crash
a backtest (mirrors the engine's "fail safe to no-trade" rule).

Indicator outputs are :class:`Val` (a ``float`` subclass that also carries the
previous bar's value), so ``crossover()`` / ``crossunder()`` work naturally:

    if crossover(ema(9), ema(21)):
        signal = "BUY"
"""

from __future__ import annotations

import math
from collections import namedtuple
from collections.abc import Sequence
from dataclasses import dataclass

from apex.indicators import engine as ind
from apex.models import Candle

#: How many trailing bars each indicator sees. Bounds per-bar cost and matches
#: how EMAs/RSI converge — older bars barely move a daily indicator.
LOOKBACK = 400

MACD = namedtuple("MACD", ["line", "signal", "hist"])
Boll = namedtuple("Boll", ["upper", "mid", "lower"])
Donchian = namedtuple("Donchian", ["upper", "lower"])
#: Auction map from a rolling volume-by-price profile (see ``_Indicators.volume_profile``).
VProfile = namedtuple("VProfile", ["poc", "vah", "val", "lvn", "width"])
#: Hidden-Markov regime read (see the ``hmm`` snippet function): filtered +
#: one-step-ahead state probabilities from a Gaussian HMM fit walk-forward.
HMMState = namedtuple("HMMState", [
    "state",                        # most-likely filtered state name
    "p_bull", "p_bear", "p_side",   # one-step-ahead probs (mean-sorted states)
    "edge",                         # p_bull - p_bear (absret mode: p_wild - p_calm)
    "stick",                        # P(stay) of the current most-likely state
    "sigma",                        # current state's emission sigma (% per bar)
    "vol_ratio",                    # sigma(hottest state) / sigma(calmest state)
])
#: Today's opening range and the prior session's range (intraday microstructure levels).
ORange = namedtuple("ORange", ["high", "low", "mid", "width"])
DayRange = namedtuple("DayRange", ["high", "low", "close"])

# Tokens that must never appear in a user snippet (basic sandbox guard).
_FORBIDDEN = (
    "__", "import", "open(", "exec(", "eval(", "compile(", "globals(",
    "locals(", "getattr", "setattr", "delattr", "vars(", "input(",
    "os.", "sys.", "subprocess", "socket", "request",
)

# Safe builtins exposed to the snippet.
_SAFE_BUILTINS = {
    "abs": abs, "min": min, "max": max, "round": round, "len": len, "sum": sum,
    "range": range, "float": float, "int": int, "bool": bool, "str": str,
    "True": True, "False": False, "None": None,
    "pow": pow, "sorted": sorted, "any": any, "all": all, "enumerate": enumerate,
    "zip": zip, "map": map, "filter": filter, "list": list, "tuple": tuple,
}


class Val(float):
    """A float that also remembers the previous bar's value (for crossovers)."""

    prev: float

    def __new__(cls, value: float, prev: float | None = None) -> Val:
        obj = super().__new__(cls, value)
        obj.prev = float(prev) if prev is not None else float(value)
        return obj


def _nan_val() -> Val:
    return Val(math.nan, math.nan)


def _clamp(value: object, lo: float, hi: float) -> float | None:
    """Coerce a snippet output to a float in [lo, hi]; None if unset/invalid."""
    if value is None:
        return None
    try:
        return max(lo, min(float(value), hi))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _now_prev(x: object) -> tuple[float, float]:
    now = float(x)  # type: ignore[arg-type]
    return now, float(getattr(x, "prev", now))


def validate_code(code: str) -> tuple[bool, str]:
    """Static safety + syntax check. Returns (ok, error_message)."""
    if not (code or "").strip():
        return False, "Strategy is empty."
    lowered = code.lower()
    for tok in _FORBIDDEN:
        if tok in lowered:
            return False, f"Disallowed token in strategy: {tok!r}"
    try:
        compile(code, "<strategy>", "exec")
    except SyntaxError as exc:
        return False, f"Syntax error on line {exc.lineno}: {exc.msg}"
    return True, ""


@dataclass
class _Indicators:
    """Per-bar indicator context over a bounded candle window."""

    candles: list[Candle]
    #: Per-bar REAL taker-flow deltas aligned with ``candles`` (Binance perp
    #: seeds; empty for instruments without an order-flow column).
    deltas: list[float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._closes = [c.close for c in self.candles]
        self._prev_closes = self._closes[:-1]
        self._prev_candles = self.candles[:-1]
        if self.deltas is None:
            self.deltas = []

    def _v(self, cur: float | None, prev: float | None) -> Val:
        if cur is None:
            return _nan_val()
        return Val(cur, prev if prev is not None else cur)

    def sma(self, period: int) -> Val:
        return self._v(ind.sma(self._closes, period), ind.sma(self._prev_closes, period))

    def ema(self, period: int) -> Val:
        return self._v(ind.ema(self._closes, period), ind.ema(self._prev_closes, period))

    def rsi(self, period: int = 14) -> Val:
        return self._v(ind.rsi(self._closes, period), ind.rsi(self._prev_closes, period))

    def atr(self, period: int = 14) -> Val:
        return self._v(ind.atr(self.candles, period), ind.atr(self._prev_candles, period))

    def adx(self, period: int = 14) -> Val:
        return self._v(ind.adx(self.candles, period), ind.adx(self._prev_candles, period))

    def macd(self, fast: int = 12, slow: int = 26, signal: int = 9) -> MACD:
        cur = ind.macd(self._closes, fast, slow, signal)
        prev = ind.macd(self._prev_closes, fast, slow, signal)
        if cur is None:
            return MACD(_nan_val(), _nan_val(), _nan_val())
        p = prev or cur
        return MACD(Val(cur[0], p[0]), Val(cur[1], p[1]), Val(cur[2], p[2]))

    def bollinger(self, period: int = 20, num_std: float = 2.0) -> Boll:
        cur = ind.bollinger(self._closes, period, num_std)
        prev = ind.bollinger(self._prev_closes, period, num_std)
        if cur is None:
            return Boll(_nan_val(), _nan_val(), _nan_val())
        p = prev or cur
        return Boll(Val(cur[0], p[0]), Val(cur[1], p[1]), Val(cur[2], p[2]))

    def highest(self, period: int) -> Val:
        highs = [c.high for c in self.candles[-period:]]
        prev = [c.high for c in self._prev_candles[-period:]]
        return self._v(max(highs) if highs else None, max(prev) if prev else None)

    def lowest(self, period: int) -> Val:
        lows = [c.low for c in self.candles[-period:]]
        prev = [c.low for c in self._prev_candles[-period:]]
        return self._v(min(lows) if lows else None, min(prev) if prev else None)

    def donchian(self, period: int) -> Donchian:
        """Donchian channel: highest CLOSE / lowest CLOSE over ``period`` bars."""
        cur = self._closes[-period:]
        prev = self._prev_closes[-period:]
        upper = self._v(max(cur) if cur else None, max(prev) if prev else None)
        lower = self._v(min(cur) if cur else None, min(prev) if prev else None)
        return Donchian(upper, lower)

    def roc(self, n: int = 1) -> Val:
        """Close-to-close % return over ``n`` bars (rate of change)."""
        if len(self._closes) <= n:
            return _nan_val()
        base = self._closes[-1 - n]
        cur = (100.0 * (self._closes[-1] - base) / base) if base else None
        prev = None
        if len(self._prev_closes) > n:
            pbase = self._prev_closes[-1 - n]
            prev = (100.0 * (self._prev_closes[-1] - pbase) / pbase) if pbase else None
        return self._v(cur, prev)

    def stdev(self, period: int) -> Val:
        """Population standard deviation of the last ``period`` closes (volatility)."""
        w = self._closes[-period:]
        if len(w) < 2:
            return _nan_val()
        mean = sum(w) / len(w)
        var = sum((x - mean) ** 2 for x in w) / len(w)
        return self._v(var ** 0.5, None)

    def vwap(self, period: int = 20) -> Val:
        """Rolling volume-weighted average price over ``period`` bars (session-proxy
        fair value). Falls back to SMA(close) if volume is unavailable/zero."""
        def _calc(bars: list[Candle]) -> float | None:
            if not bars:
                return None
            num = sum(((b.high + b.low + b.close) / 3.0) * (b.volume or 0.0) for b in bars)
            den = sum((b.volume or 0.0) for b in bars)
            if den <= 0:
                return sum(b.close for b in bars) / len(bars)
            return num / den
        return self._v(_calc(self.candles[-period:]), _calc(self._prev_candles[-period:]))

    def volume_profile(self, period: int = 120, bins: int = 30) -> VProfile:
        """Volume-by-price **auction map** over the last ``period`` bars.

        This is the heart of Auction Market Theory: where has the most *business*
        been transacted? Each bar's volume is spread uniformly across its
        ``[low, high]`` range into ``bins`` price buckets, then we read:

          * ``poc``  — Point of Control: price of the highest-volume bucket (the
            fair-value magnet; the market keeps returning to it).
          * ``vah`` / ``val`` — Value-Area High / Low: the band around the POC
            holding ~70% of total volume. Price **inside** ``[val, vah]`` is *in
            balance*; price **outside** it is *out of balance* (the only place the
            #1-scalper model takes a trade).
          * ``lvn`` — Low-Volume Node: the thinnest bucket's price — a level the
            market travels through quickly (a continuation gate / poor support).
          * ``width`` — ``vah - val`` (how tight the current balance is).

        Built from OHLCV only (no order book), so it works on every seeded series;
        when volume is missing/zero it degrades to an equal-weight TPO profile.
        """
        bars = self.candles[-period:] if period > 0 else self.candles
        if len(bars) < 3:
            return VProfile(_nan_val(), _nan_val(), _nan_val(), _nan_val(), _nan_val())
        lo = min(b.low for b in bars)
        hi = max(b.high for b in bars)
        if hi <= lo:
            v = Val(lo)
            return VProfile(v, v, v, v, Val(0.0))
        nb = max(4, int(bins))
        step = (hi - lo) / nb
        vol = [0.0] * nb
        for b in bars:
            i0 = max(0, min(nb - 1, int((max(lo, b.low) - lo) / step)))
            i1 = max(0, min(nb - 1, int((min(hi, b.high) - lo) / step)))
            w = (b.volume or 0.0) or 1.0  # equal-weight when volume is absent
            share = w / (i1 - i0 + 1)
            for k in range(i0, i1 + 1):
                vol[k] += share
        total = sum(vol)
        if total <= 0:
            v = Val((hi + lo) / 2.0)
            return VProfile(v, Val(hi), Val(lo), v, Val(hi - lo))
        poc_i = max(range(nb), key=lambda k: vol[k])
        lvn_i = min(range(nb), key=lambda k: vol[k])
        # Grow the value area out from the POC, always taking the heavier neighbour,
        # until it captures ~70% of total volume (the standard value-area rule).
        lo_i = hi_i = poc_i
        captured = vol[poc_i]
        target = 0.70 * total
        while captured < target and (lo_i > 0 or hi_i < nb - 1):
            below = vol[lo_i - 1] if lo_i > 0 else -1.0
            above = vol[hi_i + 1] if hi_i < nb - 1 else -1.0
            if above >= below:
                hi_i += 1
                captured += vol[hi_i]
            else:
                lo_i -= 1
                captured += vol[lo_i]
        poc = lo + (poc_i + 0.5) * step
        return VProfile(
            Val(poc), Val(lo + (hi_i + 1) * step), Val(lo + lo_i * step),
            Val(lo + (lvn_i + 0.5) * step), Val((hi_i - lo_i + 1) * step),
        )

    def _cvd_sum(self, bars: list[Candle]) -> float:
        """Sum of per-bar volume deltas (close-location-value × volume)."""
        d = 0.0
        for b in bars:
            rng = b.high - b.low
            if rng <= 0:
                continue
            clv = (2.0 * b.close - b.high - b.low) / rng  # −1 (closed on low) … +1 (high)
            d += clv * ((b.volume or 0.0) or 1.0)
        return d

    def cvd(self, period: int = 20) -> Val:
        """**Cumulative Volume Delta** proxy over the last ``period`` bars — the
        order-flow *pressure benchmark* the #1 scalper uses to read aggression.

        With no tick/footprint feed we approximate each bar's delta as its
        close-location-value (−1 if it closed on the low, +1 on the high) times
        its volume: a close near the high on heavy volume = aggressive buyers, near
        the low = aggressive sellers. Rising CVD = buyers leaning on the gas
        (confirming an up move / time to protect a long sooner). Carries the
        previous bar's value, so ``crossover(cvd(20), 0)`` and slope reads work.
        """
        return self._v(self._cvd_sum(self.candles[-period:]),
                        self._cvd_sum(self._prev_candles[-period:]))

    def flow(self, period: int = 20) -> Val:
        """Rolling sum of the REAL taker-flow deltas over ``period`` bars.

        Unlike :meth:`cvd` (a close-location proxy), this reads the actual
        aggressor-side imbalance the exchange reported (taker buys − taker
        sells, base units) — available on the Binance perp seeds via the
        ``delta`` data column. NaN when the instrument has no flow column.
        """
        d = self.deltas
        if not d:
            return _nan_val()
        cur = sum(d[-period:])
        prev = sum(d[:-1][-period:]) if len(d) > 1 else None
        return self._v(cur, prev)

    def flow_norm(self, period: int = 20) -> Val:
        """Net taker flow / total volume over ``period`` bars, in [−1, +1].

        A bounded, era-stationary pressure read: +0.2 means 60/40 buyer
        dominance of all volume traded in the window. NaN without flow data.
        """
        d = self.deltas
        if not d:
            return _nan_val()

        def _calc(dd: list[float], bars: list[Candle]) -> float | None:
            vol = sum((b.volume or 0.0) for b in bars[-period:])
            if vol <= 0:
                return None
            return sum(dd[-period:]) / vol

        return self._v(_calc(d, self.candles),
                       _calc(d[:-1], self._prev_candles) if len(d) > 1 else None)

    def opening_range(self, start_h: int = 13, start_m: int = 30, dur_min: int = 60) -> ORange:
        """Today's **opening range** — the high/low of the bars in the
        ``[start, start+dur_min)`` UTC window on the current bar's date. The
        foundation of an Opening-Range Breakout: a coiled session-open range that
        price then breaks out of. Returns NaN until at least one OR bar exists.
        """
        cur = self.candles[-1]
        d = cur.time.date()
        lo_m = start_h * 60 + start_m
        hi_m = lo_m + max(1, int(dur_min))
        bars = [b for b in self.candles
                if b.time.date() == d and lo_m <= (b.time.hour * 60 + b.time.minute) < hi_m]
        if not bars:
            return ORange(_nan_val(), _nan_val(), _nan_val(), _nan_val())
        hi = max(b.high for b in bars)
        lo = min(b.low for b in bars)
        return ORange(Val(hi), Val(lo), Val((hi + lo) / 2.0), Val(hi - lo))

    def prev_day_range(self) -> DayRange:
        """The **prior session's** high / low / close — the liquidity-sweep levels
        intraday algos hunt. Uses the most recent calendar date before the current
        bar's date that exists in the window. NaN if no prior day is in view."""
        cur = self.candles[-1]
        d = cur.time.date()
        prior = sorted({b.time.date() for b in self.candles if b.time.date() < d})
        if not prior:
            return DayRange(_nan_val(), _nan_val(), _nan_val())
        pd = prior[-1]
        bars = [b for b in self.candles if b.time.date() == pd]
        hi = max(b.high for b in bars)
        lo = min(b.low for b in bars)
        return DayRange(Val(hi), Val(lo), Val(bars[-1].close))

    def cvd_divergence(self, lookback: int = 12) -> int:
        """Regular **CVD divergence** over the last ``lookback`` bars — the order-flow
        "exhaustion" read. Builds the cumulative-volume-delta line across the window
        and compares the two price extremes against the CVD line at those points:

          * ``+1`` BULLISH — price prints a LOWER low but CVD prints a HIGHER low:
            sellers are exhausting into the new low (a high-quality long trigger).
          * ``-1`` BEARISH — price prints a HIGHER high but CVD a LOWER high.
          * ``0``  — no divergence.

        Computed on whatever series is loaded. On a 1H backtest it reads the 1H CVD
        sub-structure; for live use, feed it the lower-timeframe (e.g. 15m) bars to
        confirm a higher-timeframe entry. (The seeded intraday history is only deep
        enough on the 1H series, so backtests run the divergence there.)
        """
        bars = self.candles[-lookback:]
        n = len(bars)
        if n < 6:
            return 0
        cum = 0.0
        line: list[float] = []
        for b in bars:
            rng = b.high - b.low
            clv = (2.0 * b.close - b.high - b.low) / rng if rng > 0 else 0.0
            cum += clv * ((b.volume or 0.0) or 1.0)
            line.append(cum)
        half = n // 2
        lo_old = min(range(0, half), key=lambda k: bars[k].low)
        lo_new = min(range(half, n), key=lambda k: bars[k].low)
        if bars[lo_new].low < bars[lo_old].low and line[lo_new] > line[lo_old]:
            return 1
        hi_old = max(range(0, half), key=lambda k: bars[k].high)
        hi_new = max(range(half, n), key=lambda k: bars[k].high)
        if bars[hi_new].high > bars[hi_old].high and line[hi_new] < line[hi_old]:
            return -1
        return 0


def crossover(a: object, b: object) -> bool:
    """True when ``a`` crosses **above** ``b`` on this bar."""
    an, ap = _now_prev(a)
    bn, bp = _now_prev(b)
    return ap <= bp and an > bn


def crossunder(a: object, b: object) -> bool:
    """True when ``a`` crosses **below** ``b`` on this bar."""
    an, ap = _now_prev(a)
    bn, bp = _now_prev(b)
    return ap >= bp and an < bn


# ── Markov regime model (the "hedge-fund method") ───────────────────────────
# Quant-desk regime engine, exposed to snippets as ``markov(...)``. It is the
# observable Markov-chain method: label every bar Bull / Bear / Sideways from a
# rolling N-bar % return, count state-to-state transitions into a 3x3
# maximum-likelihood matrix, raise that matrix to the ``horizon`` power
# (Chapman-Kolmogorov) for an n-step forecast, then read today's row for
# tomorrow's probabilities. ``edge = P(bull) - P(bear)`` is the tradeable
# signal: its sign is direction, its size is conviction. The fit uses ONLY bars
# up to the current one, so a per-bar backtest is walk-forward by construction —
# the matrix is re-estimated every bar from data that existed before that bar.

#: Trailing bars used to fit the transition matrix (rolling, adaptive, bounded).
MARKOV_WINDOW = 1500
#: How many closes ``decide`` hands the engine each bar (window + headroom for L).
_MARKOV_SLICE = MARKOV_WINDOW + 256

Regime = namedtuple("Regime", [
    "state",                          # "BULL" | "BEAR" | "SIDE" — today's regime
    "p_bull", "p_bear", "p_side",     # forecast probabilities for +horizon bars
    "edge",                           # p_bull - p_bear  (signal: + long, - short)
    "stickiness",                     # P(stay in today's state) — regime persistence
    "sd_bull", "sd_bear", "sd_side",  # stationary distribution (long-run state mix)
])

_BEAR, _SIDE, _BULL = 0, 1, 2
#: Returned before enough history exists to fit a matrix → edge 0 → no trade.
_NEUTRAL = Regime("SIDE", 1 / 3, 1 / 3, 1 / 3, 0.0, 1 / 3, 1 / 3, 1 / 3, 1 / 3)


def _matmul3(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    """Multiply two 3x3 matrices (used to power the transition matrix)."""
    return [[sum(a[r][k] * b[k][c] for k in range(3)) for c in range(3)] for r in range(3)]


def _stationary3(p: list[list[float]], iters: int = 250) -> list[float]:
    """Long-run state mix: the vector ``v`` with ``vP = v``, via power iteration."""
    v = [1 / 3, 1 / 3, 1 / 3]
    for _ in range(iters):
        nv = [sum(v[r] * p[r][c] for r in range(3)) for c in range(3)]
        s = sum(nv) or 1.0
        nv = [x / s for x in nv]
        if max(abs(nv[k] - v[k]) for k in range(3)) < 1e-10:
            return nv
        v = nv
    return v


def compute_markov(
    closes: Sequence[float], state_lookback: int = 20,
    bull_thr: float | None = None, bear_thr: float | None = None,
    horizon: int = 1, window: int = MARKOV_WINDOW, band: float = 0.5,
) -> Regime:
    """Fit the regime transition matrix from ``closes`` and forecast ``horizon`` ahead.

    When ``bull_thr`` / ``bear_thr`` are omitted the Bull / Bear bands are scaled to
    the instrument's own volatility (``band`` × stdev of the N-bar returns), so the
    model is not tied to the subjective ±5% the video flags as its weak link and
    works as-is on indices, FX and crypto. Only past closes are read, so calling it
    once per bar yields a walk-forward (look-ahead-free) estimate.
    """
    length = max(1, int(state_lookback))
    h = max(1, int(horizon))
    closes = list(closes)
    if window > 0 and len(closes) > window + length:
        closes = closes[-(window + length):]
    n = len(closes)
    if n < length + 2:
        return _NEUTRAL

    rets = [100.0 * (closes[j] - closes[j - length]) / closes[j - length]
            for j in range(length, n) if closes[j - length]]
    if len(rets) < 2:
        return _NEUTRAL

    if bull_thr is None or bear_thr is None:
        mean = sum(rets) / len(rets)
        sigma = (sum((x - mean) ** 2 for x in rets) / len(rets)) ** 0.5
        if sigma <= 1e-9:
            return _NEUTRAL
        bull_thr = band * sigma if bull_thr is None else bull_thr
        bear_thr = -band * sigma if bear_thr is None else bear_thr

    def label(ret: float) -> int:
        if ret >= bull_thr:
            return _BULL
        if ret <= bear_thr:
            return _BEAR
        return _SIDE

    labels = [label(r) for r in rets]
    counts = [[1.0, 1.0, 1.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0]]  # Laplace smoothing
    for a, b in zip(labels[:-1], labels[1:]):
        counts[a][b] += 1.0
    p = [[v / sum(row) for v in row] for row in counts]  # row-stochastic matrix

    m = p
    for _ in range(h - 1):  # Chapman-Kolmogorov: P^horizon for an n-step forecast
        m = _matmul3(m, p)

    cur = labels[-1]
    p_bear, p_side, p_bull = m[cur][_BEAR], m[cur][_SIDE], m[cur][_BULL]
    sd = _stationary3(p)
    state = "BULL" if cur == _BULL else "BEAR" if cur == _BEAR else "SIDE"
    return Regime(state, p_bull, p_bear, p_side, p_bull - p_bear,
                  m[cur][cur], sd[_BULL], sd[_BEAR], sd[_SIDE])


# ── Gaussian Hidden-Markov regime engine ─────────────────────────────────────
# A step up from the observable ``markov`` chain: states are LATENT and inferred
# from the return distribution itself (Baum-Welch maximum-likelihood fit), so the
# model discovers the market's own regime structure — e.g. a fat-tailed
# liquidation-cascade state vs a tight consolidation state on crypto perps —
# instead of imposing fixed return-threshold labels. Exposed to snippets as
# ``hmm(...)``. Walk-forward by construction: the fit at bar *t* sees only
# closes ≤ *t*, is re-estimated every ``refit`` bars, and the filtered state
# distribution is advanced bar-by-bar with the forward recursion in between.

#: Trailing observations used to fit the HMM (bounded for per-bar cost).
HMM_WINDOW = 1000
#: Bars between Baum-Welch re-fits (the filter still updates EVERY bar).
HMM_REFIT = 96

_HMM_NEUTRAL = HMMState("SIDE", 1 / 3, 1 / 3, 1 / 3, 0.0, 1 / 3, 0.0, 1.0)


def _gauss(x: float, mu: float, var: float) -> float:
    """Gaussian pdf, floored so a fat-tail outlier can never zero the filter."""
    z = (x - mu) ** 2 / (2.0 * var)
    if z > 200.0:
        return 1e-87
    return max(math.exp(-z) / math.sqrt(2.0 * math.pi * var), 1e-87)


def _hmm_obs(closes: Sequence[float], on: str) -> list[float]:
    """Per-bar % returns from ``closes`` (``on='absret'`` → magnitudes only)."""
    obs = [100.0 * (closes[j] / closes[j - 1] - 1.0)
           for j in range(1, len(closes)) if closes[j - 1]]
    return [abs(x) for x in obs] if on == "absret" else obs


def fit_hmm(
    obs: Sequence[float], n_states: int = 3, iters: int = 8,
) -> tuple[list[float], list[list[float]], list[float], list[float]] | None:
    """Baum-Welch ML fit of a Gaussian HMM over ``obs``. Pure Python, scaled
    forward-backward, variance-floored. Returns ``(pi, A, means, vars)`` or
    ``None`` when there is too little data to fit."""
    T = len(obs)
    n = n_states
    if T < 30 * n:
        return None
    # Init: means at spread quantiles, shared global variance, sticky transitions.
    srt = sorted(obs)
    mus = [srt[int((k + 0.5) * (T - 1) / n)] for k in range(n)]
    mean = sum(obs) / T
    gvar = max(sum((x - mean) ** 2 for x in obs) / T, 1e-6)
    vars_ = [gvar] * n
    a_off = 0.10 / (n - 1)
    A = [[0.90 if r == c else a_off for c in range(n)] for r in range(n)]
    pi = [1.0 / n] * n

    for _ in range(iters):
        B = [[_gauss(x, mus[k], vars_[k]) for k in range(n)] for x in obs]
        # forward (scaled)
        alpha = [[0.0] * n for _ in range(T)]
        scale = [0.0] * T
        for k in range(n):
            alpha[0][k] = pi[k] * B[0][k]
        s = sum(alpha[0]) or 1e-300
        scale[0] = s
        alpha[0] = [a / s for a in alpha[0]]
        for t in range(1, T):
            at = alpha[t - 1]
            row = [sum(at[r] * A[r][c] for r in range(n)) * B[t][c] for c in range(n)]
            s = sum(row) or 1e-300
            scale[t] = s
            alpha[t] = [x / s for x in row]
        # backward (same scaling)
        beta = [[1.0] * n for _ in range(T)]
        for t in range(T - 2, -1, -1):
            bt1, Bt1 = beta[t + 1], B[t + 1]
            beta[t] = [sum(A[r][c] * Bt1[c] * bt1[c] for c in range(n)) / (scale[t + 1] or 1e-300)
                       for r in range(n)]
        # E-step accumulators
        gamma = [[alpha[t][k] * beta[t][k] for k in range(n)] for t in range(T)]
        for t in range(T):
            s = sum(gamma[t]) or 1e-300
            gamma[t] = [g / s for g in gamma[t]]
        xi_sum = [[0.0] * n for _ in range(n)]
        for t in range(T - 1):
            at, bt1, Bt1 = alpha[t], beta[t + 1], B[t + 1]
            tot = 0.0
            cell = [[at[r] * A[r][c] * Bt1[c] * bt1[c] for c in range(n)] for r in range(n)]
            tot = sum(sum(row) for row in cell) or 1e-300
            for r in range(n):
                for c in range(n):
                    xi_sum[r][c] += cell[r][c] / tot
        # M-step
        for r in range(n):
            den = sum(xi_sum[r]) or 1e-300
            A[r] = [xi_sum[r][c] / den for c in range(n)]
        for k in range(n):
            den = sum(gamma[t][k] for t in range(T)) or 1e-300
            mu = sum(gamma[t][k] * obs[t] for t in range(T)) / den
            var = sum(gamma[t][k] * (obs[t] - mu) ** 2 for t in range(T)) / den
            mus[k], vars_[k] = mu, max(var, 1e-6)
        pi = gamma[0][:]
    return pi, A, mus, vars_


def hmm_filter_step(
    probs: list[float], A: list[list[float]], mus: list[float],
    vars_: list[float], x: float,
) -> list[float]:
    """One forward-filter update: predict through ``A`` then condition on ``x``."""
    n = len(probs)
    up = [sum(probs[r] * A[r][c] for r in range(n)) * _gauss(x, mus[c], vars_[c])
          for c in range(n)]
    s = sum(up) or 1e-300
    return [u / s for u in up]


def hmm_read(
    params: tuple[list[float], list[list[float]], list[float], list[float]],
    probs: list[float], on: str,
) -> HMMState:
    """Build the snippet-facing :class:`HMMState` from filtered ``probs``."""
    _, A, mus, vars_ = params
    n = len(mus)
    order = sorted(range(n), key=lambda k: mus[k])      # calmest/most-bearish first
    pred = [sum(probs[r] * A[r][c] for r in range(n)) for c in range(n)]
    p_bear, p_bull = pred[order[0]], pred[order[-1]]
    p_side = max(0.0, 1.0 - p_bear - p_bull)
    cur = max(range(n), key=lambda k: probs[k])
    lo_name, hi_name = ("CALM", "WILD") if on == "absret" else ("BEAR", "BULL")
    state = lo_name if cur == order[0] else hi_name if cur == order[-1] else "SIDE"
    sig_lo = math.sqrt(vars_[order[0]]) or 1e-9
    return HMMState(state, p_bull, p_bear, p_side, p_bull - p_bear,
                    A[cur][cur], math.sqrt(vars_[cur]),
                    math.sqrt(vars_[order[-1]]) / sig_lo)


_DECISIONS = {
    "BUY": "BUY", "LONG": "BUY",
    "SELL": "SELL", "SHORT": "SELL",
    "FLAT": "FLAT", "CLOSE": "FLAT", "EXIT": "FLAT",
    "HOLD": None, "NONE": None, "": None,
}


class CompiledStrategy:
    """Compile a snippet once; evaluate it per bar to a BUY/SELL/FLAT decision."""

    def __init__(self, code: str, exo: dict[str, list[float]] | None = None) -> None:
        ok, err = validate_code(code)
        if not ok:
            raise ValueError(err)
        self._code = compile(code, "<strategy>", "exec")
        self._exo = exo or {}
        # Snippet-chosen exit geometry for the most recent decide() (None → engine
        # defaults). Lets a trend strategy push the target far and ride a winner.
        self.last_stop_mult: float | None = None
        self.last_target_rr: float | None = None
        # Optional two-stage exit: scale ``last_scale_frac`` of the position out when
        # price reaches ``last_scale_price`` (an absolute level, e.g. the POC) and, if
        # ``last_scale_be``, move the stop to break-even. None/0 → plain SL/TP.
        self.last_scale_price: float | None = None
        self.last_scale_frac: float = 0.0
        self.last_scale_be: bool = False
        # Optional trailing stop (price-distance) on the runner after a scale-out.
        self.last_trail_dist: float = 0.0
        # Walk-forward HMM cache: (states, window, refit, on) -> fit + filter state.
        # Lives on the instance so the per-bar forward filter advances O(1).
        self._hmm_cache: dict[tuple, dict] = {}

    def decide(
        self, index: int, candles: Sequence[Candle], *,
        position: int = 0, bars_held: int = 0, equity: float = 100_000.0,
        risk_pct: float = 0.0, leverage: float = 0.0,
        day_pnl_pct: float = 0.0, consec_losses: int = 0,
        consec_wins: int = 0, trades_today: int = 0,
        dd_from_peak_pct: float = 0.0, total_pnl_pct: float = 0.0,
        bars_since_scale: int = -1,
    ) -> tuple[str | None, float | None]:
        """Return ``(decision, risk)`` for bar ``index``.

        ``decision`` is "BUY"/"SELL"/"FLAT" or None (hold). ``risk`` is the per-trade
        risk % the snippet chose by setting ``risk = ...`` (None → use the run
        default). ``candles`` is the full history up to and including ``index``; the
        keyword args expose live state (``position`` 1/-1/0, ``bars_held``,
        ``equity``) and run parameters (``risk_pct`` default, ``leverage``).

        For prop-firm risk control the snippet also sees ``day_pnl_pct`` (running
        P&L since the start of the current calendar day, %), ``consec_losses`` /
        ``consec_wins`` (current closed-trade streak) and ``trades_today``.
        """
        window = list(candles[max(0, index - LOOKBACK + 1) : index + 1])
        if not window:
            return None
        bar = window[-1]
        dvals = self._exo.get("delta") or []
        dwin = list(dvals[max(0, index - LOOKBACK + 1) : index + 1]) if dvals else []
        ctx = _Indicators(window, deltas=dwin if len(dwin) == len(window) else [])
        exo_at = {name: (vals[index] if 0 <= index < len(vals) else math.nan)
                  for name, vals in self._exo.items()}

        # Markov regime sees a deeper (but still bounded, walk-forward) close
        # history so it can fit a stable transition matrix; only bars <= index.
        # Built lazily on first call so snippets that never use markov pay nothing.
        _mc: list[list[float]] = []

        def markov(state_lookback: int = 20, bull_thr: float | None = None,
                   bear_thr: float | None = None, horizon: int = 1,
                   window: int = MARKOV_WINDOW, band: float = 0.5) -> Regime:
            if not _mc:
                _mc.append([c.close for c in candles[max(0, index + 1 - _MARKOV_SLICE) : index + 1]])
            return compute_markov(_mc[0], state_lookback, bull_thr, bear_thr,
                                  horizon, window, band)

        def hmm(states: int = 3, window: int = HMM_WINDOW, refit: int = HMM_REFIT,
                on: str = "ret") -> HMMState:
            """Walk-forward Gaussian-HMM regime read at the current bar.

            Re-fits Baum-Welch every ``refit`` bars on the trailing ``window``
            returns (only bars ≤ the current one), and advances the filtered
            state distribution bar-by-bar in between, so a sequential backtest
            pays O(1) per bar. ``on='absret'`` fits return MAGNITUDES → a
            volatility-regime model (CALM/WILD) for cascade detection.
            """
            n = max(2, min(int(states), 4))
            mode = "absret" if on == "absret" else "ret"
            key = (n, int(window), max(1, int(refit)), mode)
            st = self._hmm_cache.get(key)
            bucket = index // key[2]
            if st is None or st["bucket"] != bucket or st["at"] > index:
                closes = [c.close for c in candles[max(0, index - key[1] - 1) : index + 1]]
                obs = _hmm_obs(closes, mode)
                params = fit_hmm(obs, n)
                if params is None:
                    return _HMM_NEUTRAL
                probs = list(params[0])
                for x in obs:
                    probs = hmm_filter_step(probs, params[1], params[2], params[3], x)
                st = {"bucket": bucket, "at": index, "params": params, "probs": probs}
                self._hmm_cache[key] = st
            elif st["at"] < index:
                closes = [c.close for c in candles[max(0, st["at"] - 1) : index + 1]]
                # advance over only the bars seen since the cached filter state
                new_obs = _hmm_obs(closes, mode)[-(index - st["at"]):]
                p = st["probs"]
                for x in new_obs:
                    p = hmm_filter_step(p, st["params"][1], st["params"][2], st["params"][3], x)
                st["probs"], st["at"] = p, index
            return hmm_read(st["params"], st["probs"], mode)

        ns: dict[str, object] = {
            "__builtins__": _SAFE_BUILTINS,
            # current bar (Val carries the previous bar's value for crossovers)
            "open": Val(bar.open, window[-2].open if len(window) > 1 else bar.open),
            "high": Val(bar.high, window[-2].high if len(window) > 1 else bar.high),
            "low": Val(bar.low, window[-2].low if len(window) > 1 else bar.low),
            "close": Val(bar.close, window[-2].close if len(window) > 1 else bar.close),
            "price": Val(bar.close, window[-2].close if len(window) > 1 else bar.close),
            "volume": bar.volume,
            "i": index, "n": len(candles),
            # exogenous niche variables
            "fear_and_greed": exo_at.get("fear_greed", math.nan),
            "fear_greed": exo_at.get("fear_greed", math.nan),
            "vix": exo_at.get("vix", math.nan),
            "sentiment": exo_at.get("sentiment", math.nan),
            # indicator functions
            "sma": ctx.sma, "ema": ctx.ema, "rsi": ctx.rsi, "atr": ctx.atr,
            "adx": ctx.adx, "macd": ctx.macd, "bollinger": ctx.bollinger,
            "highest": ctx.highest, "lowest": ctx.lowest,
            "donchian": ctx.donchian, "roc": ctx.roc, "stdev": ctx.stdev,
            "vwap": ctx.vwap,
            # auction-market-theory toolkit: volume-by-price map + order-flow CVD
            "volume_profile": ctx.volume_profile, "cvd": ctx.cvd,
            "cvd_divergence": ctx.cvd_divergence,
            # REAL taker-flow order-flow (Binance perp seeds): per-bar delta +
            # rolling sum / volume-normalized pressure in [−1, +1]
            "delta": exo_at.get("delta", math.nan),
            "flow": ctx.flow, "flow_norm": ctx.flow_norm,
            # macro regime overlays: % distance to the 50-day / 200-day SMA of
            # completed DAILY closes (walk-forward; 0.0 until enough days exist)
            "macro": exo_at.get("macro", math.nan),
            "macro_slow": exo_at.get("macro_slow", math.nan),
            # intraday microstructure levels (opening range + prior-session range)
            "opening_range": ctx.opening_range, "prev_day_range": ctx.prev_day_range,
            "crossover": crossover, "crossunder": crossunder,
            "markov": markov,  # hedge-fund regime engine → Regime(state, p_bull, ...)
            "hmm": hmm,        # latent-state Gaussian HMM → HMMState(state, edge, ...)
            # bar clock (UTC) for session filters
            "hour": int(bar.time.hour), "minute": int(bar.time.minute),
            "dow": int(bar.time.weekday()),
            "nan": math.nan, "isnan": math.isnan,
            # live strategy state + run parameters
            "position": int(position), "bars_held": int(bars_held), "equity": float(equity),
            "risk_pct": float(risk_pct), "leverage": float(leverage),
            # prop-firm risk state: per-day (day_pnl_pct, streaks, trades_today)
            # and account-level (dd_from_peak_pct, total_pnl_pct since inception)
            "day_pnl_pct": float(day_pnl_pct), "consec_losses": int(consec_losses),
            "consec_wins": int(consec_wins), "trades_today": int(trades_today),
            "dd_from_peak_pct": float(dd_from_peak_pct), "total_pnl_pct": float(total_pnl_pct),
            # runner state: bars since the partial scale-out (−1 if not scaled yet),
            # and a convenience flag, for a one-time velocity gate on the runner.
            "bars_since_scale": int(bars_since_scale), "scaled": bool(bars_since_scale >= 0),
            # outputs (the snippet sets these)
            "signal": None, "risk": None,
            # optional exit geometry overrides (None → engine defaults)
            "stop_mult": None, "target_rr": None,
            # optional two-stage exit (scale a fraction out at a price, BE the rest)
            "scale_at": None, "scale_frac": None, "scale_be": None,
            # optional trailing stop (price distance) on the runner after the scale
            "trail_dist": None,
        }
        try:
            exec(self._code, ns)  # noqa: S102 - sandboxed: restricted builtins + source check
        except Exception:  # fail safe to HOLD, never crash the backtest
            return None, None
        raw = ns.get("signal")
        decision = _DECISIONS.get(str(raw).strip().upper(), None) if raw is not None else None
        # The snippet may pick its own per-trade risk %; clamp it to a sane range.
        chosen = ns.get("risk")
        try:
            chosen_risk = float(chosen) if chosen is not None else None
            if chosen_risk is not None:
                chosen_risk = max(0.01, min(chosen_risk, 10.0))
        except (TypeError, ValueError):
            chosen_risk = None
        self.last_stop_mult = _clamp(ns.get("stop_mult"), 0.3, 5.0)
        self.last_target_rr = _clamp(ns.get("target_rr"), 0.2, 20.0)
        # Two-stage exit overrides: a raw price level + the fraction to scale there.
        sp_raw = ns.get("scale_at")
        try:
            self.last_scale_price = float(sp_raw) if sp_raw is not None else None  # type: ignore[arg-type]
        except (TypeError, ValueError):
            self.last_scale_price = None
        self.last_scale_frac = _clamp(ns.get("scale_frac"), 0.0, 0.95) or 0.0
        self.last_scale_be = bool(ns.get("scale_be"))
        td = ns.get("trail_dist")
        try:
            self.last_trail_dist = max(0.0, float(td)) if td is not None else 0.0  # type: ignore[arg-type]
        except (TypeError, ValueError):
            self.last_trail_dist = 0.0
        return decision, chosen_risk
