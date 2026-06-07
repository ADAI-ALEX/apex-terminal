# name: Auction Flow V5.2 (Scaled)
# description: V5.1-Hybrid execution, dialled up to use the remaining risk runway. IDENTICAL exit engine to V5.1 — bank 50% at the POC, 3-bar CVD velocity gate, break-even + 1.5-ATR trail to the VAH — but the entry size band is raised from 1.2-1.9% to 1.5-2.3% per trade, still scaled by CVD-divergence strength. Daily breaker -3.2%, lifetime backstop -9.0%, long-only, 1H, no overnight. US500.
#
# ── What changed vs V5.1 (sizing ONLY) ───────────────────────────────────────
#   The execution logic that produced V5.1's ~63% win rate is untouched: 50% scale
#   at POC, the CVD velocity gate (run only when momentum accelerates, else flatten),
#   BE + 1.5-ATR trail to the VAH. The ONLY change is the dynamic risk band:
#   1.2-1.9% -> 1.5-2.3%, to convert V5.1's drawdown headroom into more growth.
#   Risk isolation is unchanged: -3.2% daily close breaker, -9.0% lifetime backstop.
#
# ── RISK NOTE ────────────────────────────────────────────────────────────────
# Bigger size moves drawdown roughly in proportion. V5.1 ran ~7.3% max total DD
# locally; this band lifts the floor to 1.5%, so the total DD will climb toward the
# -9% backstop. The velocity gate (which cut V5.1's DD below V4's) is what keeps it
# survivable — do NOT widen the band further without re-checking the backstop.
#
# ── VERDICT (US500 1h, last 10k bars, costs ON) — SHIPPED 1H CHAMPION ─────────
# V5.1 -> V5.2 (1.5-2.3% band): return +21.8% -> +27.64%, win 62.5% (held), realised
# R:R 0.96, PF 1.60, max daily DD 3.18% -> 3.88%, max total DD 7.31% -> 8.85%, MC pass
# 83.8% -> 80.5%, breach 12.5% -> 18.8%. Shipped as the 1H production champion with
# the elevated risk EXPLICITLY ACCEPTED.
# RUNS HOT — trade with eyes open: max total DD 8.85% sits only 0.15% from the -9%
# backstop, max daily DD 3.88% nears the -4% breaker, and ~19% of Monte-Carlo paths
# breach -10%. If a smoother curve is preferred, V5.1 (1.2-1.9%, +21.8% at 7.31% DD)
# or a 1.5-2.1% band (~+26-27% at ~8.3-8.4% DD) trade a little yield for real cushion.

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
RISK_LO = 1.5        # SCALED-UP divergence-tilt risk floor (%/trade) — was 1.2
RISK_HI = 2.3        # SCALED-UP divergence-tilt risk ceiling (%/trade) — was 1.9
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
