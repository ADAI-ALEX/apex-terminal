"""Global Macro V4 (Institutional) — BTC 4H live engine for FTMO MT5.

Live port of ``apex/strategies/custom/global_macro_v4.py`` (Phase-5.4 master):
the Crypto State V2 stack on BTCUSD 240m — long-only, macro-gated momentum.
CHALLENGE_MODE toggles between the two walk-forward-validated corners of the
Phase-5.2 stability plateau (never into unvalidated space):

  * False (institutional): z24h > 0.9, flow > 0.015, day cap 4
  * True  (funding challenge): z24h > 0.8, flow > 0.01, day cap 6
    (+44% trade frequency, no losing half-year window, worst dDD 3.78 / tDD 4.93)

Mode is read from ``.env`` (``CHALLENGE_MODE``); default is the institutional
corner — the safer failure direction if the flag is missing.

Live fidelity notes:
  * ``macro`` / ``macro_slow`` = % of the last COMPLETED daily close vs the
    50-day / 200-day SMA of completed daily closes (constant intra-day,
    strictly causal — matches the seed's daily-ffill convention).
  * ``flow_norm`` prefers the REAL taker imbalance from Binance perp klines
    (the seed's data source: delta = 2·takerBuy − volume, summed / Σvolume).
    Falls back to the bounded CLV-CVD proxy on FTMO bars if Binance is
    unreachable; the active source is logged on every switch.
"""
from __future__ import annotations

import json
import urllib.request

from apex_mt5 import (
    NAN, Ctx, Decision, EngineConfig, Mt5Engine, mt5,
    atr, flow_norm_clv, isnan, load_env, env_bool, roc, sma,
)

ENV = load_env()
CHALLENGE_MODE: bool = env_bool(ENV, "CHALLENGE_MODE", default=False)

# ── validated gate corners (Phase 5.2 plateau — do not tune) ───────────────
Z_MIN = 0.8 if CHALLENGE_MODE else 0.9
Z3D_MIN = 0.5
F_MIN = 0.01 if CHALLENGE_MODE else 0.015
DAY_CAP = 6 if CHALLENGE_MODE else 4
MACRO_MIN = 3.0          # % above 50-day daily SMA
BASE_RISK = 2.8          # %/trade (V2 sizing)
HALT_DD = 7.5            # dd_from_peak halt
HALT_TOTAL = -7.0        # total-pnl halt
DAY_STOP = -2.0          # daily lock
TARGET_RR = 6.0
TREND_BARS = 24          # sma(24) on 4H closes
ATR_P = 14

_flow_source = {"name": ""}


def _binance_flow_norm(period: int = 20) -> float:
    """Real taker-flow imbalance from Binance USDT-perp 4h klines, in [−1, +1]."""
    url = ("https://fapi.binance.com/fapi/v1/klines"
           f"?symbol=BTCUSDT&interval=4h&limit={period + 2}")
    with urllib.request.urlopen(url, timeout=10) as r:
        kl = json.loads(r.read().decode())
    kl = kl[:-1][-period:]  # drop the forming kline; strictly closed bars
    vol = sum(float(k[5]) for k in kl)
    if vol <= 0 or len(kl) < period:
        return NAN
    delta = sum(2.0 * float(k[9]) - float(k[5]) for k in kl)  # taker buy − taker sell
    return delta / vol


def _flow(ctx: Ctx, log) -> float:
    """flow_norm(20): Binance real taker flow, CLV proxy as fallback."""
    try:
        f = _binance_flow_norm(20)
        if not isnan(f):
            if _flow_source["name"] != "binance":
                _flow_source["name"] = "binance"
                log.info("flow source: Binance perp taker imbalance (seed-faithful)")
            return f
    except Exception as exc:
        if _flow_source["name"] != "clv":
            log.warning("Binance flow unreachable (%s) — falling back to CLV proxy", exc)
    if _flow_source["name"] != "clv":
        _flow_source["name"] = "clv"
        log.info("flow source: CLV-CVD proxy on FTMO bars")
    return flow_norm_clv(ctx.bars, 20)


def _macro_gates(engine: Mt5Engine) -> tuple[float, float]:
    """(macro, macro_slow): % of last completed daily close vs 50d / 200d SMA."""
    days = engine.closed_bars(engine.cfg.symbol, mt5.TIMEFRAME_D1, 210)
    closes = [b.close for b in days]
    if len(closes) < 200:
        return NAN, NAN
    s50 = sma(closes, 50)
    s200 = sma(closes, 200)
    px = closes[-1]
    macro = 100.0 * (px - s50) / s50 if s50 else NAN
    macro_slow = 100.0 * (px - s200) / s200 if s200 else NAN
    return macro, macro_slow


def build() -> tuple[Mt5Engine, "Callable[[Ctx], Decision]"]:
    """Wire the engine + decision function from .env (no hardcoded credentials)."""
    cfg = EngineConfig(
        name="global_macro_v4",
        symbol=ENV.get("BTC_SYMBOL", "BTCUSD"),
        timeframe=mt5.TIMEFRAME_H4,
        magic=int(ENV.get("MAGIC_BTC", "540401")),
        warmup_bars=120,
        poll_seconds=float(ENV.get("POLL_SECONDS", "10")),
        server_utc_offset_h=int(ENV.get("SERVER_UTC_OFFSET_HOURS", "3")),
        login=int(ENV["MT5_LOGIN"]),
        password=ENV["MT5_PASSWORD"],
        server=ENV.get("MT5_SERVER", "FTMO-Demo"),
        terminal_path=ENV.get("MT5_PATH", ""),
    )
    engine = Mt5Engine(cfg)
    engine.log.info("CHALLENGE_MODE=%s → z_min=%.2f f_min=%.3f day_cap=%d",
                    CHALLENGE_MODE, Z_MIN, F_MIN, DAY_CAP)

    def on_bar(ctx: Ctx) -> Decision:
        closes = [b.close for b in ctx.bars]
        close = closes[-1]
        a = atr(ctx.bars, ATR_P)
        atrp = 100.0 * a / close if (not isnan(a) and a > 0) else NAN
        r6 = roc(closes, 6)
        r18 = roc(closes, 18)
        f = _flow(ctx, engine.log)
        trend = sma(closes, TREND_BARS)
        macro, macro_slow = _macro_gates(engine)

        z24 = r6 / (atrp * 1.8) if (not isnan(atrp)) and atrp > 0 else NAN
        z3d = r18 / (atrp * 3.12) if (not isnan(atrp)) and atrp > 0 else NAN

        ok = not (isnan(z24) or isnan(z3d) or isnan(f) or isnan(trend)
                  or isnan(macro) or isnan(macro_slow))
        enter = (ok and macro > MACRO_MIN and macro_slow > 0.0 and z24 > Z_MIN
                 and z3d > Z3D_MIN and f > F_MIN and close > trend)
        mom_dead = ok and z3d < 0.0

        halt = ctx.dd_from_peak_pct >= HALT_DD or ctx.total_pnl_pct <= HALT_TOTAL
        day_locked = ctx.day_pnl_pct <= DAY_STOP or ctx.trades_today >= DAY_CAP

        risk = BASE_RISK
        if ctx.consec_losses >= 4:
            risk *= 0.35
        elif ctx.consec_losses >= 2:
            risk *= 0.6
        if ctx.dd_from_peak_pct >= 6.0:
            risk *= 0.4
        elif ctx.dd_from_peak_pct >= 4.5:
            risk *= 0.6
        risk = round(max(0.3, risk), 2)

        stop_mult = min(5.0, max(4.0, 2.2 / atrp)) if (ok and atrp > 0) else 4.0

        engine.log.info(
            "bar %s | close=%.1f z24=%.2f z3d=%.2f f=%.4f macro=%.1f/%.1f "
            "pos=%d dd=%.2f day=%.2f trades=%d",
            ctx.bars[-1].time.strftime("%m-%d %H:%M"), close,
            z24 if ok else NAN, z3d if ok else NAN, f, macro, macro_slow,
            ctx.position, ctx.dd_from_peak_pct, ctx.day_pnl_pct, ctx.trades_today)

        if halt:
            if ctx.position != 0:
                return Decision("FLAT", reason="HALT dd/total breaker")
            return Decision("HOLD")
        if ctx.position == 0 and not day_locked and enter:
            return Decision("BUY", risk_pct=risk, stop_dist=stop_mult * a,
                            target_rr=TARGET_RR, reason="macro momentum entry")
        if ctx.position == 1 and mom_dead:
            return Decision("FLAT", reason="z3d momentum dead")
        return Decision("HOLD")

    return engine, on_bar


if __name__ == "__main__":
    eng, fn = build()
    eng.run(fn)
