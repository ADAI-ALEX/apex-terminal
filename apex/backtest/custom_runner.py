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

    def __post_init__(self) -> None:
        self._closes = [c.close for c in self.candles]
        self._prev_closes = self._closes[:-1]
        self._prev_candles = self.candles[:-1]

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

    def decide(self, index: int, candles: Sequence[Candle]) -> str | None:
        """Return "BUY"/"SELL"/"FLAT" or None (hold) for bar ``index``.

        ``candles`` is the full history up to and including ``index``.
        """
        window = list(candles[max(0, index - LOOKBACK + 1) : index + 1])
        if not window:
            return None
        bar = window[-1]
        ctx = _Indicators(window)
        exo_at = {name: (vals[index] if 0 <= index < len(vals) else math.nan)
                  for name, vals in self._exo.items()}

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
            "crossover": crossover, "crossunder": crossunder,
            "nan": math.nan, "isnan": math.isnan,
            # output
            "signal": None,
        }
        try:
            exec(self._code, ns)  # noqa: S102 - sandboxed: restricted builtins + source check
        except Exception:  # fail safe to HOLD, never crash the backtest
            return None
        raw = ns.get("signal")
        if raw is None:
            return None
        key = str(raw).strip().upper()
        return _DECISIONS.get(key, None)
