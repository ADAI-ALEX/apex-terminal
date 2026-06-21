# name: Auction Flow
# description: Auction-Market-Theory strategy (long-only) that buys a discount below
#   value in a balanced range, or a shallow pullback inside a confirmed up-auction,
#   and sizes risk dynamically off order-flow quality (CVD divergence + momentum).
#   Two-stage take-profit (partial at POC, runner to VAH, break-even stop) with a
#   daily circuit breaker and an account-level drawdown backstop. Demo strategy
#   showing the editor's volume-profile / CVD primitives — tune the constants below
#   and re-run the backtest to see the effect.

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
RISK_LO = 1.2        # risk floor (%/trade)
RISK_HI = 2.2        # risk ceiling (%/trade) — reserved for divergence-confirmed longs
RISK_FLOOR = 0.8     # never throttle below this even in a deep losing streak
DAY_BREAK = -3.2     # hard daily circuit breaker (%)
MAX_LOSS = 9.0       # account drawdown backstop (%)
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
bull_div = div > 0                   # clear bullish CVD divergence

# Strength of the CVD buying impulse, 0..1 — the fine modulation on size.
slope = cv - cv.prev
denom = max(abs(cv), abs(cv.prev), 1.0)
strength = max(0.0, min(slope / denom, 1.0)) if cv_up else 0.0

# Order-flow QUALITY, 0..1 — tilts the position size. A clean bullish CVD
# divergence (the dominant term) pushes risk toward the ceiling; its absence
# toward the floor; CVD momentum trims within that.
quality = 0.65 * (1.0 if bull_div else 0.0) + 0.35 * strength

# Location (step 1): a discount below value. Long-only.
discount = ok and close < val - DEEP * a
ranging = ok and adx_v < RANGE_ADX
up_auction = ok and ema_f > ema_s and close > ema_s and adx_v >= TREND_ADX
not_bear = ok and close > ema_s        # don't buy dips in a confirmed bear leg

# ── account governors ────────────────────────────────────────────────────────
survival = dd_from_peak_pct >= MAX_LOSS       # account backstop
day_breaker = day_pnl_pct <= DAY_BREAK        # hard daily breaker
day_locked = day_breaker or trades_today >= MAX_TRADES

# Dynamic risk, tilted by order-flow quality, throttled in a losing streak.
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
