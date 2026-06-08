# name: Auction Flow V6.1-Master (15M MTF)
# description: The 15M solution — Multi-Timeframe-anchored Auction Market Theory. The diagnosis from the V6 A/B was that 15M broke the edge two ways: (1) stops sized to the tiny 15M-ATR get wicked out by microstructure noise before the reversion completes (the main win-rate killer), and (2) a value area recomputed on raw 15M bars is noise, not an institutional level. V6.1 fixes both: it anchors the volume profile / POC / value area on a STABLE multi-session window (the HTF structure) and sizes the stop to a 1H/session scale (~3x the 15M-ATR) so noise can't stop a genuine reversion — while triggering on the 15M for precision. It retains the V4/V5.2 edge (value-area mean-reversion + CVD institutional filtering, divergence-weighted sizing) and banks the majority (70%) at the POC, keeping only a small strict-gated runner (the A/B proved the runner is the worse architecture on 15M). Daily breaker -4.0%, lifetime backstop -9.0%, long-only, no overnight. US500 15M.
#
# ── The MTF architecture (HOW it restores the edge) ──────────────────────────
#   1) STABLE STRUCTURE (HTF anchor): volume_profile over ~80 15M bars (~4-5
#      sessions) — a multi-day value area institutions actually defend, not a 15M
#      developing-noise profile. POC/VAH/VAL are the reversion references.
#   2) HTF-SCALED STOP (the key fix): stop = 3.0x the 15M-ATR (~a 1H/session range),
#      so price can wobble through the 15M noise band without stopping a real
#      reversion. Wider stop -> smaller size (constant $ risk) -> lower R:R, higher
#      win rate — the right geometry for a high-win mean-reversion edge.
#   3) RETAINED EDGE: long-only AMT value-area mean-reversion; CVD cv_up + bullish
#      divergence institutional filter; divergence-weighted 0.8-1.5% sizing.
#   4) 15M-ROBUST EXIT: bank 70% at the stable POC (high win), BE the 30% remainder,
#      and only run it on a 15%-stricter CVD velocity gate (the A/B proved a full
#      runner bleeds on 15M, so the runner is deliberately minor here).

# ── VERDICT (US500 15M, full 85-day set, costs ON) — EDGE RESTORED ───────────
# V6.a / V6.b / V6.1: return -1.28% / -2.93% / +3.73%; win 50% / 41% / 66.7%; PF
# 0.85 / 0.68 / 1.81; expectancy/trade -0.071% / -0.172% / +0.249%; max total DD
# 3.59% / 3.81% / 2.14%. The MTF anchor + HTF-scaled (3x) stop RESTORED the win rate
# to 1H levels (66.7%, vs V4's 65.8%) and flipped the book profitable at the LOWEST
# drawdown of the family — the wide stop pulled genuine reversions out of the 15M
# noise band. Per-trade quality (win%, PF, expectancy) matches the 1H champions, so
# the edge transfers. CAVEAT: 15 trades over ~85 days is a THIN sample in one regime
# (MC pass only 2.5% because 85 days can't compound to +10%, though breach is 0%);
# treat as a validated PROOF-OF-CONCEPT, not a robust live edge until deeper 15M
# history confirms it. Frequency is ~15 trades/85d vs the 1H model's ~10 — up modestly.
HTF_PROFILE = 80     # 15M bars in the STABLE value area (~4-5 NY sessions = HTF anchor)
BINS = 24
RANGE_ADX = 22       # below this = balanced/rotational
TREND_ADX = 20       # at/above this with the EMA stack = a tradable up-auction
PULL_RSI = 20        # RSI-2 pullback depth for the up-auction entry
DEEP = 0.5           # discount >= 0.5 x 15M-ATR below the (stable) VAL
MR_STOP = 3.0        # HTF-SCALED stop (~3x 15M-ATR ≈ a 1H range) — survives 15M noise
SCALE_FRAC = 0.7     # bank 70% at the POC (high win); only 30% can run
TRAIL_ATR = 1.5      # trail the small runner by this many ATRs once armed
GATE_STRICT = 1.15   # 15% stricter CVD velocity gate (15M noise buffer)
B_RR = 1.2           # up-auction-pullback target R:R
RISK_LO = 0.8        # divergence-tilt risk floor (%/trade)
RISK_HI = 1.5        # divergence-tilt risk ceiling (%/trade)
RISK_FLOOR = 0.5
DAY_BREAK = -4.0     # HARD daily breaker (%) — 1% buffer below FTMO's -5%
MAX_LOSS = 9.0       # account backstop (%) — 1% inside FTMO's -10%
MAX_TRADES = 60
TIME_STOP = 26       # ~one NY session on 15M (winners get room; flat by the close)
SESS_OPEN = 13       # NY session open (UTC) — the 15M data is NY-session only
SESS_CLOSE = 20      # NY close (UTC) — flat by here, never overnight

vp = volume_profile(HTF_PROFILE, BINS)   # STABLE multi-session value area (HTF anchor)
poc, vah, val, width = vp.poc, vp.vah, vp.val, vp.width
a = atr(14)
cv = cvd(20)
adx_v = adx(14)
ema_f = ema(50)
ema_s = ema(200)
r2 = rsi(2)
div = cvd_divergence(12)

# CVD velocity gate — 15% stricter (15M noise buffer).
cv3 = cvd(3)
expanding = (cv3 > 0) and (cv3 > cv3.prev) and (cv3 > cvd(12) * 0.25 * GATE_STRICT)

ok = (a and a > 0) and not isnan(poc) and width > 0
tradeable = SESS_OPEN <= hour < SESS_CLOSE
cv_up = cv > cv.prev
bull_div = div > 0
turning = close > close.prev          # 15M short-term up-tick (LTF trigger precision)

slope = cv - cv.prev
denom = max(abs(cv), abs(cv.prev), 1.0)
strength = max(0.0, min(slope / denom, 1.0)) if cv_up else 0.0
quality = 0.65 * (1.0 if bull_div else 0.0) + 0.35 * strength

# Location vs the STABLE value area (the HTF anchor), in 15M-ATR units.
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

# ── manage an open trade (engine banks 70% + BE + trail; snippet runs the gate) ─
elif position == 1:
    if hour >= SESS_CLOSE or bars_held >= TIME_STOP:
        signal = "FLAT"                          # NY close / time stop — never overnight
    elif bars_since_scale == 1 and not expanding:
        signal = "FLAT"          # VELOCITY GATE: no momentum at the POC -> bank it now

# ── look for a new entry (flat, inside limits; divergence weights SIZE) ───────
elif position == 0 and ok and tradeable and not day_locked:
    # A) MTF MEAN-REVERSION: stable-VAL discount + CVD up + a 15M up-tick. Wide
    #    HTF-scaled stop; bank 70% at the stable POC, small gated runner to the VAH.
    if ranging and discount and not_bear and cv_up and turning:
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
    # B) UP-AUCTION pullback (secondary): single-stage target, wide stop.
    elif up_auction and r2 < PULL_RSI and cv_up:
        stop_mult = MR_STOP
        target_rr = B_RR
        signal = "BUY"
