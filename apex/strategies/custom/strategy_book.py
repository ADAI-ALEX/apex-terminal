# name: Strategy Book (editable)
# description: Editable port of the built-in "Strategy Book" — a regime detector that switches between EMA-trend, RSI-reversion and ATR-breakout entries, taking the highest-conviction signal. View/tweak the live engine's logic here. (Exits use the engine's uniform ATR stop/target, so numbers differ slightly from the built-in book.)
#
# Mirrors apex/strategies/{regime,ema_trend,rsi_reversion,atr_breakout}.py:
#   1. Classify the regime from ADX (trend strength) + ATR rate-of-change.
#   2. Evaluate the strategies that have authority over that regime, plus the
#      always-on ATR breakout, and take the strongest (highest-confidence) signal.
#   3. Size the trade by that conviction (code-controlled risk).

# ── 1) Regime: ADX trend strength + ATR rate-of-change ───────────────────────
a = atr(14)
adx14 = adx(14)
vol_roc = abs(a - a.prev) / a.prev if (not isnan(a) and a.prev) else 0.0
if vol_roc >= 0.25:
    regime = "VOLATILE"
elif not isnan(adx14) and adx14 >= 25:
    regime = "TRENDING"
elif not isnan(adx14) and adx14 <= 20:
    regime = "RANGING"
else:
    regime = "TRENDING"   # carry the instrument's preferred regime (US500 = trending)

best_dir = "HOLD"
best_conf = 0.0

# ── 2a) EMA Trend Confluence — authority: TRENDING ───────────────────────────
e9, e21, e55 = ema(9), ema(21), ema(55)
m = macd()
r = rsi(14)
if regime == "TRENDING" and not isnan(e9) and not isnan(r) and not isnan(m.hist):
    in_band = 45 <= r <= 70
    atr_unit = a if (not isnan(a) and a > 0) else 1.0
    if e9 > e21 > e55 and m.hist > 0 and in_band:
        conf = min(0.55 + abs(e9 - e55) / close * 20 + min(abs(m.hist) / atr_unit, 1.0) * 0.15, 0.9)
        if conf > best_conf:
            best_conf, best_dir = conf, "BUY"
    elif e9 < e21 < e55 and m.hist < 0 and in_band:
        conf = min(0.55 + abs(e9 - e55) / close * 20 + min(abs(m.hist) / atr_unit, 1.0) * 0.15, 0.9)
        if conf > best_conf:
            best_conf, best_dir = conf, "SELL"

# ── 2b) RSI Mean Reversion — authority: RANGING ──────────────────────────────
u, mid, lo = bollinger(20, 2)
if regime == "RANGING" and not isnan(r) and not isnan(lo):
    prev_r = r.prev
    if prev_r < 30 <= r and close <= lo * 1.001:
        conf = min(0.62 + (30 - prev_r) * 0.01, 0.85)
        if conf > best_conf:
            best_conf, best_dir = conf, "BUY"
    elif prev_r > 70 >= r and close >= u * 0.999:
        conf = min(0.62 + (prev_r - 70) * 0.01, 0.85)
        if conf > best_conf:
            best_conf, best_dir = conf, "SELL"

# ── 2c) ATR Breakout — authority: ALL regimes (compression -> expansion) ─────
a50 = atr(50)
if not isnan(a) and not isnan(a50) and a50 > 0 and a <= a50 * 0.85:
    range_high = highest(4).prev   # range of the compression window (excl. this bar)
    range_low = lowest(4).prev
    if not isnan(range_high):
        if close > range_high and best_conf < 0.55:
            best_conf, best_dir = 0.55, "BUY"
        elif close < range_low and best_conf < 0.55:
            best_conf, best_dir = 0.55, "SELL"

# ── 3) Emit the strongest signal, sized by conviction ────────────────────────
if best_dir == "BUY" or best_dir == "SELL":
    risk = round(0.3 + best_conf * 0.6, 2)   # ~0.4%..0.85% by conviction
    signal = best_dir
else:
    signal = "HOLD"   # the engine's stop/target manages exits (the book has no exit signal)
