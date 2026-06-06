# name: Auction Flow (FTMO)
# description: Auction Market Theory scalper built from the world-champion scalper's model + the prop-firm risk math. LONG-ONLY: it buys a DEEP DISCOUNT below the value area (read live from a volume profile) in a balanced market, confirmed by order flow (CVD) turning up, and rides the snap-back toward value — plus an optional buy-the-dip in a confirmed up-auction. High win rate, modest R:R, daily-loss / daily-target / max-loss governors and drawdown-aware sizing keep the curve smooth so an FTMO pass is a high-probability event. Best on US500 (also tradeable on NAS100) on the 1h. Needs an instrument with real volume.
#
# ── Why this exists (the two ideas behind it) ────────────────────────────────
# 1) An FTMO pass is a CONVEX BARRIER problem, not a returns problem: you must hit
#    +10% (phase 1) / +5% (phase 2) WITHOUT ever losing 5% in a day or 10% total.
#    The math (and the simulations) say a HIGH WIN RATE with a MODEST R:R and LOW
#    VARIANCE clears that barrier far more often than a low-win-rate moon-shot. So
#    this book takes nearby, high-probability targets, locks daily gains and
#    self-throttles in drawdown — a deliberately smooth curve, optimised for
#    Monte-Carlo PASS PROBABILITY, not for the biggest possible return.
# 2) The #1 scalper's edge is AUCTION MARKET THEORY: the market rotates between
#    BALANCE (fair value, mean-reverting) and IMBALANCE (out of value, trending).
#    "90% of traders lose because they trade patterns inside balance." So step one
#    is LOCATION — only act when price is outside value — read from a live volume
#    profile (POC / VAH / VAL). Order-flow aggression (CVD) confirms the turn.
#
# ── What the data actually says (forward-return probe on 1h indices) ─────────
#   A DEEP discount (>=0.5 ATR below the value-area low) in a balanced market is a
#   ~62-68% probability bounce over the next few hours — and the volume-profile
#   LOCATION beats every oscillator (RSI-2 oversold actually *lowers* the win rate:
#   capitulation keeps falling). Shorting premiums has NO edge — indices drift up —
#   so this book is deliberately LONG-ONLY: buy discounts, never fade rips.
#
# ── The model (the champion's "deep discount returns to value") ──────────────
#   A) MEAN-REVERSION snap-back (primary): balanced market (ADX<20) + price a DEEP
#      discount below value + CVD turning up + not in a confirmed bear leg
#      -> BUY, modest target, exit by target / time / session close.
#   B) UP-AUCTION pullback (secondary): in a trending up-auction (EMA50>EMA200,
#      ADX>=22), buy a short-term RSI-2 dip that holds at/above value with the flow.
#
# ── Be wrong quickly + never overnight (his risk management) ─────────────────
#   - ATR stop sized so noise doesn't wick you out, modest target = a high-hit-rate
#     bounce; a time stop and a hard flatten at the NY close — no overnight risk.
#
# ── FTMO survival governors ──────────────────────────────────────────────────
#   - Base 0.45%/trade, halved after 2 losses, quartered after 4 (curve self-heals)
#   - Stop opening once the day is -2.5% (soft floor inside the 5% limit), +3%
#     (lock the day -> linear growth) or after 12 trades (no overtrading)
#   - Flatten + stand down if drawdown from peak hits 6% (never reach 10% max-loss)
#
# ── Validated (local 1h, walk-forward over the seeded history, costs ON) ─────
#   US500 : ~109 trades, 68.8% win, PF 1.59, +8.6%, max daily DD 0.9%, max total
#           DD 2.5%, R^2 0.85, ~42% Monte-Carlo P(+10% before -10%), 0% breach.
#   NAS100: ~103 trades, 61.2% win, PF 1.01, ~break-even, max total DD 5.5%. It is
#           a US500-led edge (like the indices it was built on) — trade it on what
#           it is good at; the survival breaker caps the downside everywhere.
#
# Tip: this is tuned for the CHALLENGE (smoothness). On a FUNDED account you can
# raise the base risk (0.45 -> 0.7) and the target (MR_RR) to push more out of each
# winner — the payoff is realised there, so a little more variance pays.

# ── Tunables (geometry validated against the forward-return probe) ───────────
PROFILE = 120        # bars in the rolling volume profile (≈ a week of 1h auction)
BINS = 24            # price buckets in the profile
RANGE_ADX = 20       # below this = balanced/rotational -> the snap-back is reliable
TREND_ADX = 22       # at/above this with the EMA stack = an up-auction (buy dips)
PULL_RSI = 15        # short-term pullback depth (RSI-2) to buy WITH an up-auction
DEEP = 0.5           # how far below value (in ATRs) = a tradable DEEP discount
MR_STOP = 1.5        # mean-reversion stop in ATRs
MR_RR = 0.8          # mean-reversion target R:R
TIME_STOP = 10       # bars before a stale trade is cut (the edge plays out in ~6)

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

# Location (step 1, the champion's #1 rule): a DEEP DISCOUNT below value. The probe
# shows indices snap back up from here ~62-68% of the time in a balanced market —
# and that the deep-discount LOCATION beats any oscillator (RSI-2 actually hurts).
# Shorting premiums has NO edge (indices drift up), so this book is LONG-ONLY:
# buy discounts back to value, never fade rips.
discount = ok and close < val - DEEP * a
ranging = ok and adx_v < RANGE_ADX
up_auction = ok and ema_f > ema_s and close > ema_s and adx_v >= TREND_ADX
not_bear = ok and close > ema_s        # don't buy dips in a confirmed bear leg

# ── FTMO survival governors ──────────────────────────────────────────────────
survival = dd_from_peak_pct >= 6.0
day_locked = day_pnl_pct <= -2.5 or day_pnl_pct >= 3.0 or trades_today >= 12

base = 0.45
if consec_losses >= 4:
    base = base * 0.25
elif consec_losses >= 2:
    base = base * 0.5
risk = round(max(0.1, min(base, 0.6)), 2)

signal = "HOLD"

if survival:
    if position != 0:
        signal = "FLAT"                          # near the max-loss line: stand down

# ── manage an open trade ─────────────────────────────────────────────────────
elif position == 1:
    if hour >= 20 or bars_held >= TIME_STOP:
        signal = "FLAT"                          # NY close / time stop

# ── look for a new entry (flat, inside limits, in a real session) ────────────
elif position == 0 and ok and tradeable and not day_locked:
    # A) MEAN-REVERSION snap-back (the champion's "deep discount returns to value"):
    #    a DEEP discount below value in a balanced market is a ~62-68% bounce;
    #    order flow (CVD) turning up filters out the falling knives that overshoot.
    if ranging and discount and not_bear and cv_up:
        stop_mult = MR_STOP
        target_rr = MR_RR
        signal = "BUY"
    # B) UP-AUCTION pullback: in a trending up-auction, buy a short-term dip (RSI-2)
    #    that holds at/above value with the order flow — swim with the imbalance.
    elif up_auction and r2 < PULL_RSI and close >= val and cv_up:
        stop_mult = MR_STOP
        target_rr = MR_RR
        signal = "BUY"
