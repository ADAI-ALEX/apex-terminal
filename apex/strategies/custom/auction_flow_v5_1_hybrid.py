# name: Auction Flow V5.1-Hybrid (Dynamic Velocity Gate)
# description: Hybrid of V4 (bank at fair value) and V5 (let winners run), resolving the mean-reversion "POC stall" with a real-time order-flow gate. Bank 50% at the Volume Point of Control, then — only on the POC-touch bar — read 1H CVD acceleration over the last 3 bars: if buying momentum is positive AND accelerating above its moving average, arm the runner (break-even + 1.5-ATR trail out to the VAH); otherwise flatten the remaining 50% at market and take the V4-style win. Divergence-weighted 1.2-1.9% sizing, -3.2% daily breaker, -9.0% backstop, 1H, no overnight. US500.
#
# ── The thesis ───────────────────────────────────────────────────────────────
# V5 proved a mean-reversion edge has no trend to extend: price reverts TO the POC
# and stalls, so blindly running the remainder to the VAH gives back at the trail
# what V4 banked at the POC (24% -> 17%). V5.1 only lets the runner go when the order
# flow says a real trend is underway AT fair value — capturing V4's high win rate on
# the (majority) stall cases and V5's asymmetric payout on the (minority) momentum
# cases. The gate is the institutional read V5 was missing.
#
# ── Execution logic ──────────────────────────────────────────────────────────
#   1) BASELINE: at the POC, the engine banks 50% (scale_at = POC, scale_frac = 0.5),
#      moves the remaining 50% to break-even, and arms a 1.5-ATR trailing stop with
#      the VAH as the outer target.
#   2) CVD VELOCITY GATE (one-time, on the POC-touch bar — bars_since_scale == 1):
#        cv3  = cvd(3)            # net order-flow delta over the last 3 bars
#        expanding = cv3 > 0           (buying positive)
#                and cv3 > cv3.prev    (accelerating — 3-bar delta rising)
#                and cv3 > cvd(12)*0.25 (above its moving-average pace)
#      - expanding  -> DO NOTHING: the BE + 1.5-ATR trail (already armed) rides the
#        runner toward the VAH. Let the winner extend.
#      - not expanding (flat / slowing / seller absorption) -> FLAT the runner now.
#   3) RISK LOCKED (same as V4): divergence-weighted 1.2-1.9% sizing, -3.2% daily
#      close breaker, -9.0% lifetime backstop, long-only, no overnight.
#
# Note: the engine's break-even is exactly entry; the spec's "+0.5 pips" is below
# index price granularity (~0.007% on US500) and immaterial once the 1.5-ATR trail
# engages, so BE is implemented as entry.
#
# ── VERDICT (US500 1h, last 10k bars, costs ON) — a real hybrid ──────────────
# V4 -> V5 -> V5.1: return 24.2% / 16.9% / 21.8%; win 65.8% / 57.1% / 62.5%; realised
# R:R 0.90 / 1.07 / 0.96; PF 1.73 / 1.42 / 1.60; max total DD 8.35% / 8.60% / 7.31%;
# MC pass 90.5% / 78.8% / 83.8%. The momentum gate WORKS: it recovers most of V4's
# win rate and ~5 points of return over the naive V5, confirming that filtering the
# runner by CVD acceleration beats blindly running it. But it does NOT beat V4's raw
# return — even momentum-confirmed reversion does not trend-extend far enough past
# fair value to beat banking there. Its edge is RISK: the lowest max total DD of the
# family (7.31%, a full point more cushion to the -9%/-10% walls) at a return-per-DD
# ratio (2.98) that slightly beats V4 (2.89). USE: V4 for max raw return; V5.1 when
# minimising total drawdown / tail risk matters more than the last ~2% of yield.

# ── Tunables ─────────────────────────────────────────────────────────────────
PROFILE = 120        # bars in the rolling volume profile (≈ a week of 1h auction)
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

vp = volume_profile(PROFILE, BINS)   # recent auction map: POC / value area
poc, vah, val, width = vp.poc, vp.vah, vp.val, vp.width
a = atr(14)
cv = cvd(20)
adx_v = adx(14)
ema_f = ema(50)
ema_s = ema(200)
r2 = rsi(2)
div = cvd_divergence(DIV_LOOK)       # +1 bullish / -1 bearish / 0 (sizing tilt)

# CVD velocity (the gate): is 1H buying momentum positive AND accelerating above MA?
cv3 = cvd(3)
expanding = (cv3 > 0) and (cv3 > cv3.prev) and (cv3 > cvd(12) * 0.25)

ok = (a and a > 0) and not isnan(poc) and width > 0
tradeable = SESS_OPEN <= hour < SESS_CLOSE
cv_up = cv > cv.prev
bull_div = div > 0

# Strength of the CVD buying impulse, 0..1 — the fine modulation on size.
slope = cv - cv.prev
denom = max(abs(cv), abs(cv.prev), 1.0)
strength = max(0.0, min(slope / denom, 1.0)) if cv_up else 0.0
quality = 0.65 * (1.0 if bull_div else 0.0) + 0.35 * strength

# Location (step 1): a discount below value (0.25 ATR). Long-only.
discount = ok and close < val - DEEP * a
ranging = ok and adx_v < RANGE_ADX
up_auction = ok and ema_f > ema_s and close > ema_s and adx_v >= TREND_ADX
not_bear = ok and close > ema_s

# ── FTMO survival governors ──────────────────────────────────────────────────
survival = dd_from_peak_pct >= MAX_LOSS
day_breaker = day_pnl_pct <= DAY_BREAK
day_locked = day_breaker or trades_today >= MAX_TRADES

dyn = RISK_LO + (RISK_HI - RISK_LO) * quality
if consec_losses >= 4:
    dyn = dyn * 0.5
elif consec_losses >= 2:
    dyn = dyn * 0.75
risk = round(max(RISK_FLOOR, min(dyn, RISK_HI)), 2)

signal = "HOLD"

if survival or day_breaker:
    if position != 0:
        signal = "FLAT"                          # circuit breaker: stand down

# ── manage an open trade (engine banks 50% + BE + trail; snippet runs the gate) ─
elif position == 1:
    if hour >= SESS_CLOSE or bars_held >= TIME_STOP:
        signal = "FLAT"                          # NY close / time stop — never overnight
    elif bars_since_scale == 1 and not expanding:
        signal = "FLAT"          # VELOCITY GATE: no momentum at the POC -> bank it now
    # (bars_since_scale == 1 and expanding -> hold: the armed BE + 1.5-ATR trail rides)

# ── look for a new entry (flat, inside limits; divergence weights SIZE) ───────
elif position == 0 and ok and tradeable and not day_locked:
    # A) MEAN-REVERSION: bank 50% at POC, BE the rest, arm a 1.5-ATR trail to the VAH.
    #    Whether the runner actually rides is decided by the velocity gate above.
    if ranging and discount and not_bear and cv_up:
        stop_mult = MR_STOP
        sd = a * MR_STOP
        tgt = vah if vah > close + 0.2 * a else poc      # outer target = Value-Area High
        target_rr = round(max(0.4, min((tgt - close) / sd, 8.0)), 2)
        if poc > close + 0.1 * a:
            scale_at = poc
            scale_frac = SCALE_FRAC
            scale_be = True
            trail_dist = TRAIL_ATR * a
        signal = "BUY"
    # B) UP-AUCTION pullback (secondary): single-stage target.
    elif up_auction and r2 < PULL_RSI and cv_up:
        stop_mult = MR_STOP
        target_rr = B_RR
        signal = "BUY"
