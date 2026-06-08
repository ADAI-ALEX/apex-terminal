# name: Auction Flow V6.2 (Deep-Validated 15M)
# description: V6.1 re-engineered for CROSS-REGIME robustness on a deep (6.4-year) 15M dataset. The deep data exposed that V6.1's "85-day success" was a small-sample mirage (on 6.4 years it was -6.68%, 40.5% win, PF 0.58, 9.08% DD). Root cause: the deep Dukascopy data is near-24h (~90 bars/day) vs the old NY-session-only sample (~18 bars/day), so V6.1's 80-bar profile silently became a noisy <1-day profile instead of a stable multi-day value area — the MTF anchor broke. V6.2 fixes the anchor (profile sized to the new bar density), adds a macro-trend regime gate so it does not buy dips through bear/crash regimes, and is sized to the HONEST deep-data drawdown — not the phantom 85-day runway. US500 15M, costs ON, long-only, no overnight.
#
# ── What V6.2 changes vs V6.1 (and the reasoning) ────────────────────────────
#   1) DENSITY-CORRECT ANCHOR: HTF_PROFILE = 360 (~4 days on the near-24h deep data)
#      restores a STABLE multi-day value area. V6.1's 80 was ~4 days on the old
#      NY-only sample but <1 day (pure noise) on the deep set — the actual bug.
#   2) MACRO REGIME GATE: only buy discounts in an established uptrend (price above
#      EMA-200 AND EMA-100 > EMA-200). The deep data spans the 2020 crash and 2022
#      bear, where buying 15M dips is a losing trade; the gate stands aside there.
#   3) HTF-SCALED STOP retained (3x the 15M-ATR) so 15M noise can't wick a reversion.
#   4) HONEST SIZING: divergence-tilt 0.8-1.6%/trade — there is NO phantom runway to
#      exploit; size is set to the real cross-regime drawdown, kept under the 9% stop.
#   Risk: -4.0% daily breaker, -9.0% lifetime backstop. Bank 70% at the POC + a small
#   strict-gated runner (the A/B proved the runner is the weaker tool on 15M).

# ── VERDICT (US500 15M, full 6.4-year deep set, costs ON) — EDGE IS A MIRAGE ─
# Deep cross-regime data DEMOLISHES the 15M edge. The whole 15M family loses:
#   V6.0.a -X / V6.0.b -X / V6.1 -6.68% (40.5% win, PF 0.58, 9.08% DD) /
#   V6.2 -9.09% (40.0% win, PF 0.41, 9.26% DD). V6.1's +3.73% / 66.7% on 85 days was
#   a small-sample fluke in a favourable recent bull-reversion regime. The density
#   fix + macro gate did NOT restore it — there is no robust 15M edge to restore, and
#   NO unused runway (the book already exceeds the 9% stop WHILE losing). Scaling risk
#   here would be malpractice. CONCLUSION: the auction edge lives on the 1H timeframe
#   (V5.2: +27.64% over 20 months, deep-validated). This file is retained as the
#   documented proof that deep cross-regime data kills the 15M mirage. DO NOT TRADE.
HTF_PROFILE = 360    # ~4 days on near-24h 15M — STABLE value area (density-corrected)
BINS = 30
RANGE_ADX = 24       # below this = balanced/rotational
TREND_ADX = 18       # at/above this with the EMA stack = a tradable up-auction
PULL_RSI = 20
DEEP = 0.5           # discount >= 0.5 x 15M-ATR below the (stable) VAL
MR_STOP = 3.0        # HTF-scaled stop (~3x 15M-ATR) — survives 15M noise
SCALE_FRAC = 0.7     # bank 70% at the POC (high win); only 30% can run
TRAIL_ATR = 1.5
GATE_STRICT = 1.15   # 15% stricter CVD velocity gate (15M noise buffer)
B_RR = 1.2
RISK_LO = 0.8        # honest sizing — NO phantom runway to lever into
RISK_HI = 1.6
RISK_FLOOR = 0.5
DAY_BREAK = -4.0     # HARD daily breaker (%) — 1% buffer below FTMO's -5%
MAX_LOSS = 9.0       # account backstop (%) — 1% inside FTMO's -10%
MAX_TRADES = 60
TIME_STOP = 26       # ~one NY session on 15M
SESS_OPEN = 13       # trade only the NY session (the profile still sees the full 24h)
SESS_CLOSE = 20

vp = volume_profile(HTF_PROFILE, BINS)   # STABLE multi-day value area (density-corrected)
poc, vah, val, width = vp.poc, vp.vah, vp.val, vp.width
a = atr(14)
cv = cvd(20)
adx_v = adx(14)
ema_f = ema(100)     # ~1 day (near-24h)
ema_s = ema(200)     # ~2.2 days — the macro trend
r2 = rsi(2)
div = cvd_divergence(12)

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

# Macro regime gate: only buy dips in an ESTABLISHED uptrend (stand aside in bears).
macro_up = ok and close > ema_s and ema_f > ema_s

discount = ok and close < val - DEEP * a
ranging = ok and adx_v < RANGE_ADX
up_auction = ok and ema_f > ema_s and close > ema_s and adx_v >= TREND_ADX

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
        signal = "FLAT"

elif position == 1:
    if hour >= SESS_CLOSE or bars_held >= TIME_STOP:
        signal = "FLAT"
    elif bars_since_scale == 1 and not expanding:
        signal = "FLAT"

elif position == 0 and ok and tradeable and not day_locked:
    # A) MTF MEAN-REVERSION, macro-gated: discount below the STABLE VAL in an
    #    established uptrend, CVD up. Wide stop; bank 70% at POC, small gated runner.
    if ranging and discount and macro_up and cv_up:
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
    elif up_auction and r2 < PULL_RSI and cv_up and macro_up:
        stop_mult = MR_STOP
        target_rr = B_RR
        signal = "BUY"
