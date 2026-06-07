# name: Auction Flow V2 (Challenge Mode)
# description: Aggressive, higher-velocity build of Auction Flow for the FTMO evaluation window. Same Auction-Market-Theory core (long-only, buy discounts below value, CVD-confirmed) but tuned to USE the risk capacity V1 left on the table: a relaxed 0.25-ATR entry to catch standard intraday rotations (not just rare tails), dynamic 0.8-1.25% sizing scaled by CVD buying strength, and a two-stage take-profit — bank 50% at the Point of Control and trail the rest to the Value-Area High behind a break-even stop. Hard daily -2.5% circuit breaker, long-only, no overnight holds. US500 1h.
#
# ── What changed vs V1 (and why) ─────────────────────────────────────────────
# V1 was correct but PASSIVE: ~47 trades / 2y, 68% win, PF 1.52, max daily DD
# 0.48% — leaving almost all of the risk budget unused. V2 unlocks velocity and
# capital efficiency WITHOUT abandoning the edge or the guardrails:
#   1) RELAXED ENTRY: discount of >=0.25 ATR below the Value-Area Low (was 0.5).
#      Captures everyday mean-reversion rotations, not just deep tail events.
#   2) DYNAMIC SIZING: base risk scales 0.8% -> 1.25% with the strength of the CVD
#      buying impulse (stronger order-flow confirmation = bigger size).
#   3) TWO-STAGE TAKE-PROFIT: close 50% at the POC (the fair-value magnet), flip the
#      stop on the remainder to BREAK-EVEN instantly, and trail that half up to the
#      VAH. Banks the high-probability piece, then rides risk-free for the extension.
#   4) GUARDRAILS (non-negotiable, unchanged): LONG-ONLY index bias, CVD buying
#      confirmation, a HARD daily -2.5% circuit breaker (flattens + stands down),
#      strict intraday flat (no overnight holds), plus the 6% max-loss backstop.
#
# ── Validated (US500 1h, last 10,000 bars 2024-09 .. 2026-06, costs ON) ──────
#   V1 -> V2:  trades 48 -> 73 (+52%),  return +2.7% -> +14.8%,  win 66.7% -> 65.8%,
#   PF 1.44 -> 1.68,  max DAILY DD 0.92% -> 2.16% (under the 2.5% cap),  max total
#   DD 2.3% -> 5.0%,  Monte-Carlo P(+10% before -10%) 0.2% -> 83.8%, breach 0.8%.
#   Velocity + capital efficiency unlocked while the win rate and edge held.
#   Knobs: trim RISK_HI (1.25 -> ~1.1) for a fatter daily-DD cushion; tighten
#   PULL_RSI (20 -> 12) for fewer, higher-quality trend-pullback trades.
#
# Needs an instrument with real volume (US500/NAS100/EURUSD 1h). The two-stage exit
# uses the engine's scale_at / scale_frac / scale_be hooks.

# ── Tunables ─────────────────────────────────────────────────────────────────
# NB: a LONG profile is what makes "value" a real auction fair-value level — short
# profiles just track price and the discount edge collapses. So frequency comes
# from a SECOND validated archetype (uptrend RSI-2 dips), not from loosening value.
PROFILE = 120        # bars in the rolling volume profile (≈ a week of 1h auction)
BINS = 24            # price buckets in the profile
RANGE_ADX = 20       # below this = balanced/rotational -> the snap-back is reliable
TREND_ADX = 20       # at/above this with the EMA stack = a tradable up-auction
PULL_RSI = 20        # short-term pullback depth (RSI-2) to buy WITH an up-auction
DEEP = 0.25          # RELAXED: >=0.25 ATR below VAL counts as a tradable discount
MR_STOP = 1.5        # protective stop in ATRs
B_RR = 1.0           # up-auction-pullback target R:R (single-stage)
RISK_LO = 0.8        # dynamic risk floor (%/trade)
RISK_HI = 1.25       # dynamic risk ceiling (%/trade)
DAY_BREAK = -2.5     # HARD daily circuit breaker (%) — flatten + stand down
MAX_TRADES = 40      # daily trade cap (high: this is the velocity build)
TIME_STOP = 12       # bars before a stale trade is cut (no overnight anyway)

vp = volume_profile(PROFILE, BINS)   # recent auction map: POC / value area
poc, vah, val, width = vp.poc, vp.vah, vp.val, vp.width
a = atr(14)
cv = cvd(20)
adx_v = adx(14)
ema_f = ema(50)
ema_s = ema(200)
r2 = rsi(2)

ok = (a and a > 0) and not isnan(poc) and width > 0
tradeable = 7 <= hour < 20           # London + NY (skip thin Asia: bad profiles)
cv_up = cv > cv.prev                 # order flow turning up (buyers on the gas)

# Strength of the CVD buying impulse, 0..1 — drives dynamic position size.
slope = cv - cv.prev
denom = max(abs(cv), abs(cv.prev), 1.0)
strength = max(0.0, min(slope / denom, 1.0)) if cv_up else 0.0

# Location (step 1): a discount below value (relaxed to 0.25 ATR). Long-only —
# shorting premiums has no edge on up-drifting indices.
discount = ok and close < val - DEEP * a
ranging = ok and adx_v < RANGE_ADX
up_auction = ok and ema_f > ema_s and close > ema_s and adx_v >= TREND_ADX
not_bear = ok and close > ema_s        # don't buy dips in a confirmed bear leg

# ── FTMO survival governors ──────────────────────────────────────────────────
survival = dd_from_peak_pct >= 6.0           # account max-loss backstop
day_breaker = day_pnl_pct <= DAY_BREAK       # HARD daily circuit breaker
day_locked = day_breaker or trades_today >= MAX_TRADES

# Dynamic risk: 0.8%..1.25% with CVD strength, throttled back in a losing streak.
dyn = RISK_LO + (RISK_HI - RISK_LO) * strength
if consec_losses >= 4:
    dyn = dyn * 0.5
elif consec_losses >= 2:
    dyn = dyn * 0.75
risk = round(max(0.4, min(dyn, RISK_HI)), 2)

signal = "HOLD"

if survival or day_breaker:
    if position != 0:
        signal = "FLAT"                          # circuit breaker: stand down

# ── manage an open trade (engine handles the POC scale-out + BE stop) ────────
elif position == 1:
    if hour >= 20 or bars_held >= TIME_STOP:
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
    #    buy a sharp RSI-2 dip with the order flow turning up. This is a separate,
    #    probe-validated ~58% archetype that fires far more often than the deep
    #    discount — it lifts trade count without diluting the core mean-reversion.
    elif up_auction and r2 < PULL_RSI and cv_up:
        stop_mult = MR_STOP
        target_rr = B_RR
        signal = "BUY"
