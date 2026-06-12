# name: Auction Flow V6.0.a-Base (15M)
# description: Phase-2 timeframe compression — the BASE (no-runner) architecture on the 15-minute chart. Volume profile / POC / value area are generated on 15M. Execution is the pure full-exit baseline: when price hits the POC, bank 100% of the position — no scale-out, no runner, no trail. Divergence-weighted 0.8-1.4% sizing (lower, because 15M trades far more often). Daily breaker -4.0%, lifetime backstop -9.0%, long-only, no overnight. US500 15M. A/B partner of V6.b-Hybrid.
#
# ── A/B test design ──────────────────────────────────────────────────────────
# V6.a and V6.b are IDENTICAL except for the exit: same 15M profile, same entries,
# same 0.8-1.4% divergence-tilt sizing, same -4.0%/-9.0% guardrails. V6.a banks 100%
# at the POC (high win rate, no runner); V6.b scales 50% then runs a CVD-velocity-
# gated trailing runner to the VAH. The contrast isolates which exit survives 15M
# chop. Everything timeframe-sensitive (ATR stops/targets, EMAs, profile) adapts to
# 15M automatically because it is computed on the 15M bars the backtester feeds.

# ── VERDICT (US500 15M, full 85-day set, costs ON) — edge does NOT compress ──
# V6.a -1.28% (18 trades, 50% win, PF 0.85); V6.b -2.93% (17 trades, 41% win, PF
# 0.68). BOTH 15M engines LOSE money — the deep-discount auction edge lives on 1H /
# daily and does not survive 15M chop (the intraday "value area" is dominated by
# microstructure noise). The BASE (this file, full-exit-at-POC) degrades more
# gracefully than the hybrid runner. Caveats: only ~85 days of 15M data exist (one
# regime, ~18 trades — not statistically robust). Do NOT trade either on 15M; keep
# the auction strategies on 1H (V5.2 champion). Retained as the documented A/B.
#
# ── Tunables (15M) ───────────────────────────────────────────────────────────
PROFILE = 64         # 15M bars in the volume profile (~3.5 NY-session days)
BINS = 20
RANGE_ADX = 20       # below this = balanced/rotational -> the snap-back is reliable
TREND_ADX = 20       # at/above this with the EMA stack = a tradable up-auction
PULL_RSI = 20        # short-term pullback depth (RSI-2) to buy WITH an up-auction
DEEP = 0.25          # >=0.25 ATR below VAL counts as a tradable discount
DIV_LOOK = 12        # CVD-divergence lookback (15M bars) — sizing tilt
MR_STOP = 1.5        # protective stop in ATRs
B_RR = 1.0           # up-auction-pullback target R:R
RISK_LO = 0.8        # divergence-tilt risk floor (%/trade) — lower for 15M frequency
RISK_HI = 1.4        # divergence-tilt risk ceiling (%/trade)
RISK_FLOOR = 0.5     # never throttle below this even in a deep losing streak
DAY_BREAK = -4.0     # HARD daily breaker (%) — 1% buffer below FTMO's -5%
MAX_LOSS = 9.0       # account backstop (%) — 1% inside FTMO's -10%
MAX_TRADES = 60      # daily trade cap (15M is higher frequency)
TIME_STOP = 20       # bars before a stale trade is cut (~5h on 15M)
SESS_OPEN = 13       # NY session open (UTC) — the 15M data is NY-session only
SESS_CLOSE = 20      # NY close (UTC) — flat by here, never overnight

vp = volume_profile(PROFILE, BINS)   # 15M auction map: POC / value area
poc, vah, val, width = vp.poc, vp.vah, vp.val, vp.width
a = atr(14)
cv = cvd(20)
adx_v = adx(14)
ema_f = ema(50)
ema_s = ema(200)
r2 = rsi(2)
div = cvd_divergence(DIV_LOOK)

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

# ── manage an open trade (no runner: the POC target banks 100%) ──────────────
elif position == 1:
    if hour >= SESS_CLOSE or bars_held >= TIME_STOP:
        signal = "FLAT"                          # NY close / time stop — never overnight

# ── look for a new entry (flat, inside limits; divergence weights SIZE) ───────
elif position == 0 and ok and tradeable and not day_locked:
    # A) MEAN-REVERSION: full take-profit AT the POC (bank 100%, no runner).
    if ranging and discount and not_bear and cv_up:
        stop_mult = MR_STOP
        sd = a * MR_STOP
        target_rr = round(max(0.4, min((poc - close) / sd, 8.0)), 2)   # target = POC
        signal = "BUY"
    # B) UP-AUCTION pullback (secondary): single-stage target.
    elif up_auction and r2 < PULL_RSI and cv_up:
        stop_mult = MR_STOP
        target_rr = B_RR
        signal = "BUY"
