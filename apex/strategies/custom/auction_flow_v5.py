# name: Auction Flow V5 (Asymmetric Trend-Extension)
# description: Part B of the model — trade some win rate for asymmetric R:R to break the return ceiling. Same Auction-Market-Theory core (long-only, 0.25-ATR discount below value, divergence-weighted 1.2-1.9% sizing) but the EXIT is rebuilt to let winners run: at the POC, bank only 25% (covers costs), flip the rest to a BREAK-EVEN stop, then trail it by 1.5 ATR all the way out to the Value-Area High. Win rate is allowed to drift to ~48-55% in exchange for a realised R:R near 1.5-2.0. Daily breaker -3.5%, lifetime backstop -9.0%, 1H, no overnight. US500.
#
# ── What changed vs V4 (the asymmetry, item by item) ─────────────────────────
#   1) ASYMMETRIC PROFIT CAPTURE: no more full take-profit at the POC. When price
#      reaches the POC, scale just 25% out (secure baseline costs), move the stop on
#      the remaining 75% to BREAK-EVEN, then TRAIL that runner by 1.5 ATR up toward
#      the VAH. Winners trend-extend instead of being cut at fair value.
#   2) LOWER WIN-RATE ACCEPTED: cutting fewer trades early lets more give a little
#      back to the trailing stop, so the win rate drifts down (~48-55%) on purpose —
#      the bigger average winner is meant to more than pay for it (target R:R 1.5-2.0).
#   3) SIZING UNCHANGED FROM V4 (intentionally): divergence-weighted 1.2-1.9%/trade,
#      so any change in yield is attributable to the R:R pivot ALONE, not to size.
#   4) GUARDRAILS: daily close-based breaker -3.5%, lifetime backstop -9.0%, no
#      overnight holds, long-only.
#
# ── VERDICT (US500 1h, last 10k bars, costs ON): the asymmetry UNDERPERFORMS ──
# V4 -> V5: return +24.2% -> +16.9%, win 65.8% -> 57.1%, realised R:R 0.90 -> 1.07,
# PF 1.73 -> 1.42, expectancy 0.33% -> 0.24%, MC pass 90.5% -> 78.8%. The R:R rose
# and the win rate fell exactly as intended, but the R:R only reached ~1.07 (not the
# 1.5-2.0 target) and the win-rate loss swamped it. WHY: this is a MEAN-REVERSION
# edge — price reverts TO value (the POC) and stalls there; it does not trend-extend
# out to the VAH, so "letting the runner go" just gives back, via the trailing stop,
# what V4 banked at the POC. ~0.9 R:R is the SIGNATURE of the edge, not a fixable
# inefficiency. Asymmetric trend-extension is the right tool for a MOMENTUM edge, not
# this one. KEEP V4 (full/half take-profit at the POC) as the production exit; this
# file is retained as the documented experiment that proves the point.
#
# Uses the engine's scale_at / scale_frac / scale_be + trail_dist hooks. The runner
# exits at the VAH target OR the 1.5-ATR trailing stop, whichever comes first; the
# break-even floor means the 75% can never turn the trade into a loss after the POC.

# ── Tunables ─────────────────────────────────────────────────────────────────
PROFILE = 120        # bars in the rolling volume profile (≈ a week of 1h auction)
BINS = 24            # price buckets in the profile
RANGE_ADX = 20       # below this = balanced/rotational -> the snap-back is reliable
TREND_ADX = 20       # at/above this with the EMA stack = a tradable up-auction
PULL_RSI = 20        # short-term pullback depth (RSI-2) to buy WITH an up-auction
DEEP = 0.25          # >=0.25 ATR below VAL counts as a tradable discount
DIV_LOOK = 12        # CVD-divergence lookback (1h bars)
MR_STOP = 1.5        # protective stop in ATRs
SCALE_FRAC = 0.25    # bank only 25% at the POC (was 50%) — let the rest run
TRAIL_ATR = 1.5      # trail the runner's stop by this many ATRs after the scale
B_RR = 1.5           # up-auction-pullback target R:R (raised from 1.0 to let it run)
RISK_LO = 1.2        # divergence-tilt risk floor (%/trade) — unchanged from V4
RISK_HI = 1.9        # divergence-tilt risk ceiling (%/trade)
RISK_FLOOR = 0.8     # never throttle below this even in a deep losing streak
DAY_BREAK = -3.5     # HARD daily circuit breaker (%)
MAX_LOSS = 9.0       # account backstop (%) — 1% inside FTMO's -10%
MAX_TRADES = 50      # daily trade cap
TIME_STOP = 18       # bars before a stale trade is cut (longer: winners need room)
SESS_OPEN = 7        # London open (UTC) — start of the tradeable window
SESS_CLOSE = 20      # NY session close (UTC) — flat by here, never overnight

vp = volume_profile(PROFILE, BINS)   # recent auction map: POC / value area
poc, vah, val, width = vp.poc, vp.vah, vp.val, vp.width
a = atr(14)
cv = cvd(20)
adx_v = adx(14)
ema_f = ema(50)
ema_s = ema(200)
r2 = rsi(2)
div = cvd_divergence(DIV_LOOK)       # +1 bullish / -1 bearish / 0

ok = (a and a > 0) and not isnan(poc) and width > 0
tradeable = SESS_OPEN <= hour < SESS_CLOSE     # London open + NY session
cv_up = cv > cv.prev                 # order flow turning up (buyers on the gas)
bull_div = div > 0                   # clean bullish CVD divergence

# Strength of the CVD buying impulse, 0..1 — the fine modulation on size.
slope = cv - cv.prev
denom = max(abs(cv), abs(cv.prev), 1.0)
strength = max(0.0, min(slope / denom, 1.0)) if cv_up else 0.0
# Order-flow QUALITY tilts size toward the ceiling on divergence-confirmed longs.
quality = 0.65 * (1.0 if bull_div else 0.0) + 0.35 * strength

# Location (step 1): a discount below value (0.25 ATR). Long-only.
discount = ok and close < val - DEEP * a
ranging = ok and adx_v < RANGE_ADX
up_auction = ok and ema_f > ema_s and close > ema_s and adx_v >= TREND_ADX
not_bear = ok and close > ema_s        # don't buy dips in a confirmed bear leg

# ── FTMO survival governors ──────────────────────────────────────────────────
survival = dd_from_peak_pct >= MAX_LOSS       # account backstop (-9.0%)
day_breaker = day_pnl_pct <= DAY_BREAK        # HARD daily breaker (-3.5%)
day_locked = day_breaker or trades_today >= MAX_TRADES

# Dynamic risk: 1.2%..1.9% tilted by order-flow quality, throttled in a losing streak.
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

# ── manage an open trade (engine handles the scale-out + BE + trailing stop) ──
elif position == 1:
    if hour >= SESS_CLOSE or bars_held >= TIME_STOP:
        signal = "FLAT"                          # NY close / time stop — never overnight

# ── look for a new entry (flat, inside limits; divergence weights SIZE) ───────
elif position == 0 and ok and tradeable and not day_locked:
    # A) MEAN-REVERSION with an ASYMMETRIC trend-extension exit: bank 25% at the POC,
    #    BE the rest, then trail 1.5 ATR out to the VAH. Let the winner run.
    if ranging and discount and not_bear and cv_up:
        stop_mult = MR_STOP
        sd = a * MR_STOP
        tgt = vah if vah > close + 0.2 * a else poc      # outer target = Value-Area High
        target_rr = round(max(0.4, min((tgt - close) / sd, 8.0)), 2)
        if poc > close + 0.1 * a:
            scale_at = poc                                # stage 1: 25% at the POC ...
            scale_frac = SCALE_FRAC
            scale_be = True                               # ... BE the 75% ...
            trail_dist = TRAIL_ATR * a                    # ... then trail it 1.5 ATR
        signal = "BUY"
    # B) UP-AUCTION pullback (secondary): a longer single-stage target lets it run too.
    elif up_auction and r2 < PULL_RSI and cv_up:
        stop_mult = MR_STOP
        target_rr = B_RR
        signal = "BUY"
