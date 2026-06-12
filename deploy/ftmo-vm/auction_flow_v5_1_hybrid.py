"""Auction Flow V5.1-Hybrid (Dynamic Velocity Gate) — US500 1H live engine for FTMO MT5.

Live port of ``apex/strategies/custom/auction_flow_v5_1_hybrid.py`` — the US500
leg of the validated two-pillar V4 Institutional blend. Long-only Auction-Market
mean reversion: buy a deep discount (≥0.25 ATR below the Value-Area Low) in a
balanced market with rising CVD; bank 50% at the POC, move to break-even, and
let the runner ride a 1.5-ATR trail toward the VAH ONLY if the 3-bar CVD
velocity gate confirms real momentum at fair value — otherwise flatten.

This leg ships UNCHANGED in both CHALLENGE and institutional modes (its V5.1
sizing is already the validated envelope).

Live fidelity notes:
  * Session hours are UTC (London open 07 → NY close 20); the engine converts
    FTMO server time (EET, ``SERVER_UTC_OFFSET_HOURS``) to UTC on every bar.
  * CVD/profile use MT5 tick volume with the same CLV proxy the backtest used.
"""
from __future__ import annotations

from apex_mt5 import (
    NAN, Ctx, Decision, EngineConfig, Mt5Engine, mt5,
    adx, atr, cvd, cvd_divergence, cvd_prev, ema, isnan, load_env, rsi,
    volume_profile,
)

ENV = load_env()

# ── Tunables (validated — do not tune) ─────────────────────────────────────
PROFILE = 120        # bars in the rolling volume profile (~a week of 1h auction)
BINS = 24
RANGE_ADX = 20       # below this = balanced/rotational -> the snap-back is reliable
TREND_ADX = 20       # at/above this with the EMA stack = a tradable up-auction
PULL_RSI = 20        # short-term pullback depth (RSI-2) to buy WITH an up-auction
DEEP = 0.25          # >=0.25 ATR below VAL counts as a tradable discount
DIV_LOOK = 12        # CVD-divergence lookback (1h bars) — sizing tilt
MR_STOP = 1.5        # protective stop in ATRs
SCALE_FRAC = 0.5     # bank 50% at the POC (the baseline win)
TRAIL_ATR = 1.5      # trail the runner by this many ATRs once it is armed
B_RR = 1.2           # up-auction-pullback target R:R (single-stage)
RISK_LO = 1.2        # divergence-tilt risk floor (%/trade)
RISK_HI = 1.9        # divergence-tilt risk ceiling (%/trade)
RISK_FLOOR = 0.8     # never throttle below this even in a deep losing streak
DAY_BREAK = -3.2     # HARD daily circuit breaker (%)
MAX_LOSS = 9.0       # account backstop (%) — 1% inside FTMO's -10%
MAX_TRADES = 50
TIME_STOP = 18       # bars before a stale trade is cut (winners need room)
SESS_OPEN = 7        # London open (UTC)
SESS_CLOSE = 20      # NY close (UTC) — flat by here, never overnight


def build() -> tuple[Mt5Engine, "Callable[[Ctx], Decision]"]:
    """Wire the engine + decision function from .env (no hardcoded credentials)."""
    cfg = EngineConfig(
        name="auction_flow_v5_1",
        symbol=ENV.get("US500_SYMBOL", "US500"),
        timeframe=mt5.TIMEFRAME_H1,
        magic=int(ENV.get("MAGIC_US500", "540402")),
        warmup_bars=PROFILE + 100,
        poll_seconds=float(ENV.get("POLL_SECONDS", "10")),
        server_utc_offset_h=int(ENV.get("SERVER_UTC_OFFSET_HOURS", "3")),
        login=int(ENV["MT5_LOGIN"]),
        password=ENV["MT5_PASSWORD"],
        server=ENV.get("MT5_SERVER", "FTMO-Demo"),
        terminal_path=ENV.get("MT5_PATH", ""),
        # FTMO inactivity watchdog rides THIS leg only (US500 = the liquid
        # nudge instrument; hourly loop; BTC leg keeps watchdog_days=0).
        watchdog_days=int(ENV.get("WATCHDOG_DAYS", "10")),
    )
    engine = Mt5Engine(cfg)

    def on_bar(ctx: Ctx) -> Decision:
        bars = ctx.bars
        closes = [b.close for b in bars]
        close = closes[-1]
        hour = ctx.hour_utc

        vp = volume_profile(bars, PROFILE, BINS)
        poc, vah, val, width = vp.poc, vp.vah, vp.val, vp.width
        a = atr(bars, 14)
        cv = cvd(bars, 20)
        cv_p = cvd_prev(bars, 20)
        adx_v = adx(bars, 14)
        ema_f = ema(closes, 50)
        ema_s = ema(closes, 200)
        r2 = rsi(closes, 2)
        div = cvd_divergence(bars, DIV_LOOK)

        # CVD velocity (the gate): buying momentum positive AND accelerating
        cv3 = cvd(bars, 3)
        cv3_p = cvd_prev(bars, 3)
        cv12 = cvd(bars, 12)
        expanding = (cv3 > 0) and (cv3 > cv3_p) and (cv3 > cv12 * 0.25)

        ok = (not isnan(a) and a > 0) and not isnan(poc) and width > 0
        tradeable = SESS_OPEN <= hour < SESS_CLOSE
        cv_up = cv > cv_p
        bull_div = div > 0

        # Strength of the CVD buying impulse, 0..1 — fine modulation on size.
        slope = cv - cv_p
        denom = max(abs(cv), abs(cv_p), 1.0)
        strength = max(0.0, min(slope / denom, 1.0)) if cv_up else 0.0
        quality = 0.65 * (1.0 if bull_div else 0.0) + 0.35 * strength

        discount = ok and close < val - DEEP * a
        ranging = ok and adx_v < RANGE_ADX
        up_auction = ok and ema_f > ema_s and close > ema_s and adx_v >= TREND_ADX
        not_bear = ok and close > ema_s

        # ── FTMO survival governors ────────────────────────────────────
        survival = ctx.dd_from_peak_pct >= MAX_LOSS
        day_breaker = ctx.day_pnl_pct <= DAY_BREAK
        day_locked = day_breaker or ctx.trades_today >= MAX_TRADES

        dyn = RISK_LO + (RISK_HI - RISK_LO) * quality
        if ctx.consec_losses >= 4:
            dyn *= 0.5
        elif ctx.consec_losses >= 2:
            dyn *= 0.75
        risk = round(max(RISK_FLOOR, min(dyn, RISK_HI)), 2)

        engine.log.info(
            "bar %s utc%02d | close=%.1f poc=%.1f val=%.1f vah=%.1f adx=%.1f "
            "cv3=%.0f exp=%s pos=%d held=%d sscale=%d dd=%.2f day=%.2f",
            bars[-1].time.strftime("%m-%d %H:%M"), hour, close, poc, val, vah,
            adx_v, cv3, expanding, ctx.position, ctx.bars_held,
            ctx.bars_since_scale, ctx.dd_from_peak_pct, ctx.day_pnl_pct)

        if survival or day_breaker:
            if ctx.position != 0:
                return Decision("FLAT", reason="circuit breaker")
            return Decision("HOLD")

        # ── manage an open trade (engine banks 50% + BE + trail) ──────
        if ctx.position == 1:
            if hour >= SESS_CLOSE or ctx.bars_held >= TIME_STOP:
                return Decision("FLAT", reason="session close / time stop")
            if ctx.bars_since_scale == 1 and not expanding:
                return Decision("FLAT", reason="velocity gate: no momentum at POC")
            return Decision("HOLD")

        # ── look for a new entry (flat, inside limits) ─────────────────
        if ctx.position == 0 and ok and tradeable and not day_locked:
            # A) MEAN-REVERSION: bank 50% at POC, BE the rest, 1.5-ATR trail to VAH.
            if ranging and discount and not_bear and cv_up:
                sd = a * MR_STOP
                tgt = vah if vah > close + 0.2 * a else poc
                target_rr = round(max(0.4, min((tgt - close) / sd, 8.0)), 2)
                dec = Decision("BUY", risk_pct=risk, stop_dist=sd,
                               target_rr=target_rr, reason="deep discount MR")
                if poc > close + 0.1 * a:
                    dec.scale_at = poc
                    dec.scale_frac = SCALE_FRAC
                    dec.scale_be = True
                    dec.trail_dist = TRAIL_ATR * a
                return dec
            # B) UP-AUCTION pullback (secondary): single-stage target.
            if up_auction and r2 < PULL_RSI and cv_up:
                return Decision("BUY", risk_pct=risk, stop_dist=a * MR_STOP,
                                target_rr=B_RR, reason="up-auction pullback")
        return Decision("HOLD")

    return engine, on_bar


if __name__ == "__main__":
    eng, fn = build()
    eng.run(fn)
