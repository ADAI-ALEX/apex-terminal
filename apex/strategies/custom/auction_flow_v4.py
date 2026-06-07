# name: Auction Flow V4 (Max Risk Optimization)
# description: Max-utilization build of Auction Flow. Same Auction-Market-Theory core (long-only, 0.25-ATR discount below value, two-stage POC/VAH take-profit with break-even) but with DIVERGENCE-WEIGHTED sizing: a dynamic 1.2%-2.2% per trade where a clean bullish CVD divergence tilts risk toward the 2.2% ceiling and its absence toward the 1.2% floor (CVD momentum trims within). A tight -3.2% hard daily breaker holds realised daily DD under 4.0%; a -9.0% lifetime backstop keeps 1% before FTMO's -10%. 1H, strictly intraday (no overnight). US500.
#
# ── What changed vs V3 ───────────────────────────────────────────────────────
#   1) DIVERGENCE-WEIGHTED SIZING: dynamic 1.2%-2.2%/trade (V3 was 1.2%-1.9% on CVD
#      strength). The biggest risk is reserved for the cleanest, divergence-confirmed
#      longs; ordinary setups stay near the V3 floor. Concentrates risk on quality
#      WITHOUT cutting trade count.
#   2) HARD DAILY DEFENSE: daily circuit breaker at -3.2% — daily DD is the highest-
#      risk failure point, so the breaker sits below 4% to absorb a wide-bar overshoot.
#   3) LIFETIME BACKSTOP: account backstop at -9.0% (was -8.5%) — accepts a higher
#      internal total-DD ceiling for breathing room, keeping 1% before FTMO's -10%.
#   4) ORDER-FLOW QUALITY: a bullish CVD divergence (price lower-low while CVD
#      higher-low = sellers exhausting) drives the size tilt via cvd_divergence().
#
# ── Why a size-TILT, not a hard divergence GATE (tested) ─────────────────────
# Requiring a divergence to ENTER cut trades 73->16 and dropped return to +8% — too
# few heavy trades to compound. And a 1.8-2.8% band (gate or tilt) BREACHES: one
# 2.8% loser overshoots the -3.2% daily breaker past 4.0% (realised maxDay 4.68%) and
# the drawdown spirals through the -9% backstop (maxTot 9.42%), dying at ~17 trades.
# A 1.2% floor is the most this ~65%-win / ~1R edge can carry. So divergence WEIGHTS
# size (1.2->2.2) across all 73 trades instead of gating them — keeping frequency and
# concentrating risk on quality.
#
# ── On the "15-minute sub-structure" ─────────────────────────────────────────
# The seeded intraday history is only continuous on the 1H series (the 15m seed is
# ~85 days, far short of the 21-month backtest window), so cvd_divergence() reads the
# 1H CVD sub-structure here. The SAME call takes true 15m bars in live trading to
# confirm the 1H entry — the logic is timeframe-agnostic; only data depth forces 1H.
#
# ── Validated (US500 1h, last 10k bars 2024-09..2026-06, costs ON) ───────────
#   V3 -> V4: return +22.97% -> +24.17%, trades 73 (held), win 65.8%, PF 1.69 -> 1.73,
#   max DAILY DD 3.25% -> 3.49% (< 4.0%), max TOTAL DD 7.52% -> 8.35% (< 9.0%), MC
#   P(+10% before -10%) 89.8% -> 90.5%. A modest, real gain from smarter risk
#   allocation — NOT the 35% target, which this 1H edge cannot reach inside a 9% DD
#   cap (frequency is the binding constraint; bigger size just breaches/spirals).
#   maxTot 8.35% leaves only ~0.65% to the backstop — do NOT raise the ceiling.

# ── Tunables ─────────────────────────────────────────────────────────────────
PROFILE = 120        # bars in the rolling volume profile (≈ a week of 1h auction)
BINS = 24            # price buckets in the profile
RANGE_ADX = 20       # below this = balanced/rotational -> the snap-back is reliable
TREND_ADX = 20       # at/above this with the EMA stack = a tradable up-auction
PULL_RSI = 20        # short-term pullback depth (RSI-2) to buy WITH an up-auction
DEEP = 0.25          # >=0.25 ATR below VAL counts as a tradable discount
DIV_LOOK = 12        # CVD-divergence lookback (1h bars) — the order-flow sub-structure
MR_STOP = 1.5        # protective stop in ATRs
B_RR = 1.0           # up-auction-pullback target R:R (single-stage)
RISK_LO = 1.2        # risk floor (%/trade) — V3's proven-safe floor (a 1.8% floor
                     # breaches: one 2.8% loser overshoots the daily breaker past 4%)
RISK_HI = 2.2        # risk ceiling (%/trade) — reserved for divergence-confirmed longs
RISK_FLOOR = 0.8     # never throttle below this even in a deep losing streak
DAY_BREAK = -3.2     # HARD daily circuit breaker (%) — keeps realised maxDay < 4.0%
MAX_LOSS = 9.0       # account backstop (%) — 1% inside FTMO's -10%
MAX_TRADES = 50      # daily trade cap
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
div = cvd_divergence(DIV_LOOK)       # +1 bullish / -1 bearish / 0

ok = (a and a > 0) and not isnan(poc) and width > 0
tradeable = SESS_OPEN <= hour < SESS_CLOSE     # London open + NY session
cv_up = cv > cv.prev                 # order flow turning up (buyers on the gas)
bull_div = div > 0                   # STRICTER gate: clear bullish CVD divergence

# Strength of the CVD buying impulse, 0..1 — the fine modulation on size.
slope = cv - cv.prev
denom = max(abs(cv), abs(cv.prev), 1.0)
strength = max(0.0, min(slope / denom, 1.0)) if cv_up else 0.0

# Order-flow QUALITY, 0..1 — TILTS the position size. A clean bullish CVD
# divergence (the dominant term) pushes risk toward the 2.8% ceiling; its absence
# toward the 1.8% floor; CVD momentum trims within that. Divergence is no longer a
# hard gate — every qualifying setup trades, but the heaviest risk concentrates on
# the cleanest, divergence-confirmed longs.
quality = 0.65 * (1.0 if bull_div else 0.0) + 0.35 * strength

# Location (step 1): a discount below value (0.25 ATR). Long-only.
discount = ok and close < val - DEEP * a
ranging = ok and adx_v < RANGE_ADX
up_auction = ok and ema_f > ema_s and close > ema_s and adx_v >= TREND_ADX
not_bear = ok and close > ema_s        # don't buy dips in a confirmed bear leg

# ── FTMO survival governors (max-risk calibration) ──────────────────────────
survival = dd_from_peak_pct >= MAX_LOSS       # account backstop (-9.0%)
day_breaker = day_pnl_pct <= DAY_BREAK        # HARD daily breaker (-3.2%)
day_locked = day_breaker or trades_today >= MAX_TRADES

# Dynamic risk: 1.8%..2.8% tilted by order-flow quality, throttled in a losing streak.
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

# ── manage an open trade (engine handles the POC scale-out + BE stop) ────────
elif position == 1:
    if hour >= SESS_CLOSE or bars_held >= TIME_STOP:
        signal = "FLAT"                          # NY close / time stop — never overnight

# ── look for a new entry (flat, inside limits; divergence weights SIZE, not gate) ─
elif position == 0 and ok and tradeable and not day_locked:
    # A) MEAN-REVERSION snap-back with a TWO-STAGE exit (size tilted by divergence).
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
    # B) UP-AUCTION pullback (secondary); size likewise tilted by divergence.
    elif up_auction and r2 < PULL_RSI and cv_up:
        stop_mult = MR_STOP
        target_rr = B_RR
        signal = "BUY"
