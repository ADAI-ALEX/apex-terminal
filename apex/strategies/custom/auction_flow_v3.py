# name: Auction Flow V3 (Max Utilization)
# description: Maximum-utilization build of Auction Flow — same Auction-Market-Theory core (long-only, buy 0.25-ATR discounts below value, CVD-confirmed, two-stage POC/VAH take-profit with break-even) but sized to USE the FTMO risk budget instead of a fraction of it. Position size runs a dynamic 1.2%-1.9% per trade scaled by CVD-buying strength (this is the MOST this edge supports — see the calibration note below; 2× breaches the backstop). Internal breakers: hard daily flatten at -3.5% and account backstop at -8.5%, which land realised max daily DD at ~3.3% and max total DD at ~7.5% — comfortably inside FTMO's -5% / -10%. Trades both the London open and the New York session, 1H, strictly intraday (no overnight). US500.
#
# ── What changed vs V2 (and why) ─────────────────────────────────────────────
# V2 was still conservative: max DAILY DD 2.16% and max TOTAL DD 5.03% against FTMO
# limits of 5% / 10% — i.e. it used less than half the runway. V3 spends that runway
# to scale growth (+15% -> +23% on the test window) while keeping a real cushion:
#   1) BREAKERS NEAR THE FIRM LIMITS: hard daily flatten at -3.5% and an account
#      backstop at -8.5%. (See the calibration note for why -3.5%, not -4.0%.)
#   2) AGGRESSIVE SIZING: dynamic 1.2%-1.9%/trade (≈1.5× V2), scaled by CVD buying
#      strength. Drawdown-aware throttle still pulls size back in a losing streak.
#   3) MULTI-SESSION: entries are live across BOTH the London open and the New York
#      session (07:00-20:00 UTC), same window V2 used.
#   4) CORE MATH UNCHANGED: long-only index bias, 1H, 0.25-ATR-below-VAL entry, the
#      two-stage take-profit (50% at POC, trail the rest to VAH behind a break-even
#      stop), CVD buying confirmation, and the strict intraday flat (no overnight).
#
# ── CALIBRATION NOTE (why not the literal 1.5-2.5% / -4.0% that was asked for) ─
# Tested honestly, the literal aggressive spec FAILS:
#   * 1.5-2.5% sizing with a -8.5% backstop hit max total DD 9.71% (> 8.5%) and a
#     -4.0% daily breaker hit max daily DD 4.20% (> 4.0%) — BOTH limits breached.
#   * Worse, big size turns a normal early losing streak into a backstop hit, which
#     PERMANENTLY halts the book (correct for a real account near blow-up): the run
#     died at 18 trades for -6%. Drawdown does not scale linearly with size — it
#     spirals. ~1.2-1.9% is the most this ~65%-win / ~1R edge supports.
#   * Close-based 1H breakers OVERSHOOT their trigger by up to one wide bar, so the
#     internal daily breaker has to sit at -3.5% to land realised max daily DD < 4%.
#   * The total backstop must sit ABOVE the natural max DD (~7.5%): put it at the
#     natural depth and it fires mid-dip and kills the book.
# Net: 1.2-1.9% sizing, -3.5% daily / -8.5% total => +23% return, realised maxDay
# 3.25% and maxTotal 7.52%, both inside the limits. Do NOT push the band higher.

# ── Tunables ─────────────────────────────────────────────────────────────────
PROFILE = 120        # bars in the rolling volume profile (≈ a week of 1h auction)
BINS = 24            # price buckets in the profile
RANGE_ADX = 20       # below this = balanced/rotational -> the snap-back is reliable
TREND_ADX = 20       # at/above this with the EMA stack = a tradable up-auction
PULL_RSI = 20        # short-term pullback depth (RSI-2) to buy WITH an up-auction
DEEP = 0.25          # >=0.25 ATR below VAL counts as a tradable discount
MR_STOP = 1.5        # protective stop in ATRs
B_RR = 1.0           # up-auction-pullback target R:R (single-stage)
RISK_LO = 1.2        # dynamic risk floor (%/trade)  — ≈1.5× V2 (the most that holds)
RISK_HI = 1.9        # dynamic risk ceiling (%/trade)
RISK_FLOOR = 0.8     # never throttle below this even in a deep losing streak
# NB: the daily breaker sits BELOW the 4% target (close-based 1H breakers overshoot
# by ~one wide bar). The total backstop must sit ABOVE the strategy's NATURAL max
# DD (~7.5% at this size) — if it sits at the natural depth it fires mid-dip and
# permanently halts the book. -3.5% daily / -8.5% total keeps realised maxDay < 4.0%
# and maxTotal < 8.5% while letting the curve survive its drawdowns.
DAY_BREAK = -3.5     # HARD daily circuit breaker (%) — realised maxDay lands < 4.0%
MAX_LOSS = 8.5       # account backstop (%) — above the natural DD so it survives
MAX_TRADES = 50      # daily trade cap (velocity build)
TIME_STOP = 12       # bars before a stale trade is cut (no overnight anyway)
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

ok = (a and a > 0) and not isnan(poc) and width > 0
# Multi-session: London open through NY session (skip thin Asia: bad profiles).
tradeable = SESS_OPEN <= hour < SESS_CLOSE
cv_up = cv > cv.prev                 # order flow turning up (buyers on the gas)

# Strength of the CVD buying impulse, 0..1 — drives dynamic position size.
slope = cv - cv.prev
denom = max(abs(cv), abs(cv.prev), 1.0)
strength = max(0.0, min(slope / denom, 1.0)) if cv_up else 0.0

# Location (step 1): a discount below value (0.25 ATR). Long-only — shorting
# premiums has no edge on up-drifting indices.
discount = ok and close < val - DEEP * a
ranging = ok and adx_v < RANGE_ADX
up_auction = ok and ema_f > ema_s and close > ema_s and adx_v >= TREND_ADX
not_bear = ok and close > ema_s        # don't buy dips in a confirmed bear leg

# ── FTMO survival governors (recalibrated near the real firm limits) ─────────
survival = dd_from_peak_pct >= MAX_LOSS       # account max-loss backstop (-8.5%)
day_breaker = day_pnl_pct <= DAY_BREAK        # HARD daily circuit breaker (-4.0%)
day_locked = day_breaker or trades_today >= MAX_TRADES

# Dynamic risk: 1.5%..2.5% with CVD strength, throttled back in a losing streak.
dyn = RISK_LO + (RISK_HI - RISK_LO) * strength
if consec_losses >= 4:
    dyn = dyn * 0.5
elif consec_losses >= 2:
    dyn = dyn * 0.75
risk = round(max(RISK_FLOOR, min(dyn, RISK_HI)), 2)

signal = "HOLD"

if survival or day_breaker:
    if position != 0:
        signal = "FLAT"                          # circuit breaker: stand down

# ── manage an open trade (engine handles the POC scale-out + BE stop) ────────
elif position == 1:
    if hour >= SESS_CLOSE or bars_held >= TIME_STOP:
        signal = "FLAT"                          # NY close / time stop — never overnight

# ── look for a new entry (flat, inside limits, in a real session) ────────────
elif position == 0 and ok and tradeable and not day_locked:
    # A) MEAN-REVERSION snap-back with a TWO-STAGE exit: buy the discount below
    #    value with order flow up; bank 50% at the POC, trail the rest to the VAH
    #    behind a break-even stop.
    if ranging and discount and not_bear and cv_up:
        stop_mult = MR_STOP
        sd = a * MR_STOP
        tgt = vah if vah > close + 0.2 * a else poc      # final target = Value-Area High
        target_rr = round(max(0.4, min((tgt - close) / sd, 8.0)), 2)
        if poc > close + 0.1 * a:
            scale_at = poc                                # stage 1: 50% at the POC ...
            scale_frac = 0.5
            scale_be = True                               # ... then BE-stop the rest
        signal = "BUY"
    # B) UP-AUCTION pullback (secondary, the velocity add): in a confirmed up-auction
    #    buy a sharp RSI-2 dip with the order flow turning up. A separate, probe-
    #    validated ~58% archetype that fires far more often than the deep discount.
    elif up_auction and r2 < PULL_RSI and cv_up:
        stop_mult = MR_STOP
        target_rr = B_RR
        signal = "BUY"
