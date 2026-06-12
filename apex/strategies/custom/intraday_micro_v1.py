# name: Intraday Micro V1 (15M Momentum Trend-Ride)
# description: A NET-NEW, PROBE-VALIDATED 15M US500 engine. A 6.4-year forward-return probe proved the low-timeframe edge is LONG MOMENTUM CONTINUATION (price above VWAP keeps going up: vwapDev>2 -> 58% over 2h; break PDH/OR-high in an uptrend -> ~57%) while fading weakness LOSES. That edge is a small high-probability DRIFT — too thin to monetise with a fixed stop/target (noise > drift), so the only structure that works is FAT-TAIL TREND-FOLLOWING: enter momentum in an uptrend, cut the chop-day losers small, and TRAIL from entry so the rare big trend days run to many R and pay for everything. Long-only, NY session, no overnight. Daily breaker -4.0%, lifetime backstop -9.0%. US500 15M.
#
# ── The edge + the geometry (why a pure trail, not stop/target) ──────────────
#   The momentum drift (58% / +1.9 bps over 2h) is smaller than 15M noise, so any
#   fixed exit either realises losers' full stop (tight) or eats rare catastrophe
#   stops (wide). Trend-following sidesteps this: a modest initial stop caps each
#   loss, and a trail-from-entry lets winners compound on trend days. Low win rate,
#   high R:R, fat right tail — the canonical momentum payoff and the alpha that
#   justifies prop liquidation risk.

# ── VERDICT (US500 15M, full 6.4-year deep set, costs ON) — NET EDGE ~ ZERO ──
# A forward-return probe proved the edge is real (long momentum: vwapDev>2 -> 58% up)
# but exhaustive iteration (8 momentum builds: ORB, loose-ORB, momentum, time-exit,
# pure-trail, onset, dual-onset, PDH-break) all CONVERGE to break-even: PF 0.92-1.00,
# best this build PF 1.00 / -0.03% / 45.8% win / avg R:R 1.06, maxTot 9.1%. avg R:R
# ~1 across every config means there is NO fat tail — US500 does not sustain intraday
# trends to ride. The momentum DRIFT (+1.9 bps/2h) is too thin to clear the noise +
# spread. Combined with the auction (reversion) family losing on the same 6.4 years
# (V6.0-6.2 all -6 to -9%), the conclusion is firm: 15M US500 intraday is efficiently
# priced — the tradeable edge lives on 1H (V5.2: +1.36%/mo, MC9 76.7%). This file is
# the best-achievable 15M result + the probe-validated momentum engine, retained as a
# rigorous documented finding. DO NOT trade for alpha; deploy V5.2 on 1H.
#
# ── Tunables (15M) ───────────────────────────────────────────────────────────
VWAP_P = 40          # rolling VWAP (~10h) — intraday institutional reference
EMA_TREND = 50       # ~12h trend
PUSH = 0.2           # how far above VWAP (ATRs) confirms momentum (not a fade)
EXPAND = 1.0         # the breakout bar must expand > this x ATR (committed break)
STOP_ATR = 2.0       # initial stop in ATRs (modest — caps each loser)
TRAIL_ATR = 3.5      # WIDE trail from entry — hold through pullbacks, catch the tail
FAR_RR = 12.0        # nominal far target; the TRAIL / session-close does the exiting
RISK_LO = 1.0        # dynamic risk floor (%/trade)
RISK_HI = 2.0        # dynamic risk ceiling (%/trade), scaled by momentum strength
RISK_FLOOR = 0.5
DAY_BREAK = -4.0     # HARD daily breaker (%) — 1% buffer below FTMO's -5%
MAX_LOSS = 9.0       # account backstop (%) — pull our own plug before -10%
MAX_TRADES = 5       # momentum re-entries per day (ride strong trend days)
TIME_STOP = 40       # hard cap (~10h) — winners get room; flat by the close anyway
ENTRY_CLOSE = 19     # stop opening new trades after this hour (UTC)
SESS_CLOSE = 20      # flat by here — never overnight

a = atr(14)
vw = vwap(VWAP_P)
ema_t = ema(EMA_TREND)
cv = cvd(20)
orh = opening_range(13, 30, 60).high
pdh = prev_day_range().high

ok = (a and a > 0) and not isnan(vw) and not isnan(ema_t) and not isnan(orh)
cv_up = cv > cv.prev
uptrend = ok and close > vw and close > ema_t          # institutional uptrend
expansion = ok and (high - low) > EXPAND * a           # a committed breakout bar
# Trend-day ONSET (catch the start, not the extension): a FRESH break of the
# opening-range high OR the PRIOR-DAY high — the probe's strongest momentum signals
# (break>PDH 57.1% up). A break of a real level, not a mid-move chase.
onset_or = ok and close > orh and close.prev <= orh
onset_pdh = ok and (not isnan(pdh)) and close > pdh and close.prev <= pdh
onset = onset_or or onset_pdh
after_open = (hour > 14) or (hour == 14 and minute >= 30)
in_window = ok and after_open and hour < ENTRY_CLOSE

# ── prop survival governors ──────────────────────────────────────────────────
survival = dd_from_peak_pct >= MAX_LOSS
day_breaker = day_pnl_pct <= DAY_BREAK
day_locked = day_breaker or trades_today >= MAX_TRADES

# Size scales with momentum strength (distance above VWAP).
stretch = ((close - vw) / a) if (a and a > 0) else 0.0
q = max(0.0, min((stretch - PUSH) / 2.0, 1.0))
dyn = RISK_LO + (RISK_HI - RISK_LO) * q
if consec_losses >= 4:
    dyn = dyn * 0.5
elif consec_losses >= 3:
    dyn = dyn * 0.7
risk = round(max(RISK_FLOOR, min(dyn, RISK_HI)), 2)

signal = "HOLD"

if survival or day_breaker:
    if position != 0:
        signal = "FLAT"                          # circuit breaker: stand down

# ── manage: the engine trails from entry; we only enforce no-overnight ───────
elif position == 1:
    if hour >= SESS_CLOSE or bars_held >= TIME_STOP:
        signal = "FLAT"                          # session close / hard time cap

# ── look for a LONG momentum entry; ride it with a trail-from-entry ──────────
elif position == 0 and in_window and not day_locked:
    if uptrend and onset and cv_up and expansion:
        stop_mult = STOP_ATR
        target_rr = FAR_RR
        trail_dist = TRAIL_ATR * a               # pure wide trail from entry (no scale)
        signal = "BUY"
