# name: Auction Flow V6.b-Hybrid (15M)
# description: Phase-2 timeframe compression — the V5.2 HYBRID (gated-runner) architecture on the 15-minute chart. Volume profile / POC / value area on 15M. Execution = V5.2: bank 50% at the POC, then a CVD velocity gate (15% STRICTER here to reject rogue 15M volume spikes) decides whether to arm the BE + 1.5-ATR trail to the VAH or flatten the runner. Divergence-weighted 0.8-1.4% sizing (matched to V6.a). Daily breaker -4.0%, lifetime backstop -9.0%, long-only, no overnight. US500 15M. A/B partner of V6.a-Base.
#
# ── A/B test design ──────────────────────────────────────────────────────────
# Identical to V6.a-Base except the EXIT: same 15M profile, same entries, same
# 0.8-1.4% divergence-tilt sizing, same -4.0%/-9.0% guardrails. V6.a banks 100% at
# the POC; V6.b scales 50% then runs the velocity-gated trailing runner to the VAH.
# The contrast isolates which exit survives 15M chop.
#
# ── Noise buffering (15M) ────────────────────────────────────────────────────
# 15M order flow is noisier than 1H, so the velocity gate threshold is raised 15%
# (GATE_STRICT = 1.15): the runner only arms when 3-bar CVD momentum is positive,
# accelerating, AND exceeds 1.15x its moving-average pace — filtering rogue 15M
# volume spikes that would otherwise fake a breakout.

# ── VERDICT (US500 15M, full 85-day set, costs ON) — runner is WORSE on 15M ──
# V6.b -2.93% (17 trades, 41% win, PF 0.68) vs V6.a-Base -1.28% (50% win, PF 0.85).
# BOTH lose, but the gated runner is the WORSE of the two: 15M noise amplifies the
# give-back a reversion runner suffers, and even a 15%-stricter velocity gate cannot
# conjure momentum the edge does not have. Confirms the 1H lesson at higher frequency
# (asymmetry needs a trend edge). Caveats: ~85 days / ~17 trades only. Do NOT trade on
# 15M; keep the auction family on 1H (V5.2). Retained as the documented A/B.
#
# ── Tunables (15M) ───────────────────────────────────────────────────────────
PROFILE = 64         # 15M bars in the volume profile (~3.5 NY-session days)
BINS = 20
RANGE_ADX = 20
TREND_ADX = 20
PULL_RSI = 20
DEEP = 0.25
DIV_LOOK = 12
MR_STOP = 1.5
SCALE_FRAC = 0.5     # bank 50% at the POC (the baseline win)
TRAIL_ATR = 1.5      # trail the runner by this many ATRs once it is armed
GATE_STRICT = 1.15   # 15% stricter CVD velocity gate (15M noise buffer)
B_RR = 1.2
RISK_LO = 0.8        # matched to V6.a
RISK_HI = 1.4
RISK_FLOOR = 0.5
DAY_BREAK = -4.0     # HARD daily breaker (%) — 1% buffer below FTMO's -5%
MAX_LOSS = 9.0       # account backstop (%) — 1% inside FTMO's -10%
MAX_TRADES = 60
TIME_STOP = 20
SESS_OPEN = 13       # NY session open (UTC) — the 15M data is NY-session only
SESS_CLOSE = 20

vp = volume_profile(PROFILE, BINS)   # 15M auction map: POC / value area
poc, vah, val, width = vp.poc, vp.vah, vp.val, vp.width
a = atr(14)
cv = cvd(20)
adx_v = adx(14)
ema_f = ema(50)
ema_s = ema(200)
r2 = rsi(2)
div = cvd_divergence(DIV_LOOK)

# CVD velocity gate — 15% stricter than V5.2 (the 15M noise buffer).
cv3 = cvd(3)
expanding = (cv3 > 0) and (cv3 > cv3.prev) and (cv3 > cvd(12) * 0.25 * GATE_STRICT)

ok = (a and a > 0) and not isnan(poc) and width > 0
tradeable = SESS_OPEN <= hour < SESS_CLOSE
cv_up = cv > cv.prev
bull_div = div > 0

slope = cv - cv.prev
denom = max(abs(cv), abs(cv.prev), 1.0)
strength = max(0.0, min(slope / denom, 1.0)) if cv_up else 0.0
quality = 0.65 * (1.0 if bull_div else 0.0) + 0.35 * strength

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
    if ranging and discount and not_bear and cv_up:
        stop_mult = MR_STOP
        sd = a * MR_STOP
        tgt = vah if vah > close + 0.2 * a else poc
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
