# Apex Algo — Prop-Challenge Strategy (FTMO 2-Step, $100k)

> Research source-of-truth for passing and keeping a **2-step $100,000** prop account.
> Pairs with `docs/PROP_FIRM_PLAN.md` (instruments + R:R math) and the live
> `RISK_PROFILES` in `apex/config.py`. The thesis: **one regime-adaptive meta-strategy
> that switches tactics by market state**, sized so the drawdown rules can't be hit.

---

## 1. The exact rules we must satisfy

| Constraint | FTMO 2-step $100k | In £/$ on $100k | Our internal limit (buffer) |
|---|---|---|---|
| Phase-1 profit target | **+10%** | +$10,000 | reached, then stop pushing |
| Phase-2 profit target | **+5%** | +$5,000 | reached, then stop |
| Max **daily** loss | **−5%** | −$5,000 (from day-start equity) | **−4%** hard (PropGuard liquidates ~−3.5%) |
| Max **overall** loss | **−10%** | −$10,000 (from initial) | **−8%** hard (PropGuard liquidates ~−7.5%) |
| Min trading days | **4** | — | spread entries over ≥ 5 days |
| Time limit | **Unlimited** | — | no need to rush → variance is the enemy, not time |

**The single most important consequence:** with *unlimited* time, the optimal play is
**low risk per trade + consistency**, not big swings. A +10% target with a −5%
daily / −10% total leash is comfortably reachable at **0.25–0.5%/day** over ~4–8 weeks
while making a rule breach statistically near-impossible.

> Daily loss is measured from **start-of-day equity** (the higher of balance/equity at
> the FTMO 5pm-CET reset). Overall loss is from the **initial $100k** (static for FTMO,
> not a trailing peak). `PropGuard` already models both (`apex/risk/prop_guard.py`);
> for FTMO set `total` against the initial balance, not a high-water peak — see §6.

---

## 2. Position sizing that makes a breach (near) impossible

Risk per trade `r = 0.4%` of equity ($400 on $100k). With max **3** concurrent
positions and a streak-throttle (halve after 3 losses):

- Worst *uncorrelated* simultaneous heat ≈ 3 × 0.4% = **1.2%** floating.
- It takes ~**9 consecutive full-risk losses** to reach −3.6% (and the throttle makes
  losses 7–9 cost half), so the **−4% daily governor** trips long before the −5% rule.
- The **−8% internal total** trips well before the −10% rule, leaving a 2% gap for
  slippage/gaps.

A losing day is therefore bounded to roughly **−1.5% to −2.5%**, never the −5% breach.
This is the whole game: **the sizing is the strategy's safety; the breakers are the
backstop.**

---

## 3. The regime-adaptive meta-strategy

A **Regime Detector** (`apex/strategies/regime.py`, ADX + ATR rate-of-change) classifies
each instrument every 5 minutes as `TRENDING / RANGING / VOLATILE`, and **gates which
sub-strategy has authority**. This is the dynamic switching the challenge needs — the
system trades the *method that fits the current market*, and **stands aside** when no
method fits.

| Regime (ADX / ATR-RoC) | Authority | Logic | Tuned R:R | Why it fits |
|---|---|---|---|---|
| **TRENDING** (ADX > 25) | EMA Trend Confluence | EMA 9>21>55, MACD rising, RSI 45–70, pullback entry | **1 : 1.8** | rides directional moves; trend days are where the 10% comes from |
| **RANGING** (ADX < 20) | RSI Mean Reversion | RSI cross 30↑ near lower Bollinger, ATR active | **1 : 1.1** | high win-rate scalps in chop; keeps the equity curve climbing on quiet days |
| **VOLATILE / breakout** (ATR-RoC high) | ATR Breakout | 3+ compression candles → range break + sentiment confirm | **1 : 2.5** | catches expansion; small size because slippage risk is highest here |
| **No clear regime** | — none — | stand aside | — | not trading is a position; protects the daily limit |

**Claude (optional brain)** sits *after* the strategy + risk gate as a veto/confidence
layer (Tier-2 Signal Evaluator): it can downgrade to NO_TRADE on macro context
(pre-FOMC/CPI/NFP), never upgrade. With the AI brain off, the Python rules run alone —
fully functional, zero AI cost.

---

## 4. Dynamic adaptation levers (beyond strategy switching)

1. **Volatility-scaled sizing** — stake = `riskGBP / (ATR14 × stop_mult)`. Automatically
   smaller in high vol, larger in calm → constant £ risk regardless of regime.
2. **Daily-loss governor** — at −2% on the day, halve size; at −3%, new entries off for
   the day; −4% PropGuard flattens + locks. Protects the −5% rule in tiers.
3. **Daily profit lock** — once the day is **+1.5%**, tighten to break-even-plus and stop
   opening new risk (lock the gain; don't give it back). Consistency > heroics.
4. **Session filter** — trade each instrument only in its liquid hours (US500 14:30–21:00
   UK; EUR/USD London+NY overlap). Avoids thin-book slippage that wrecks backtests-vs-live.
5. **News blackout** — flatten / no-new-entry 30 min around tier-1 macro prints
   (`news_blackout_minutes`); the largest source of gap-through-stop risk.
6. **Correlation cap** — treat US500/NAS100 as one bucket (don't stack correlated longs).

---

## 5. Phase-by-phase plan (the part most bots get wrong)

- **Phase 1 (target +10%):** run the full regime book at `r = 0.4%`. Expectancy ≈
  +0.45·r/trade × ~4 trades/day ≈ **+0.8%/day gross potential**, realistically banking
  **~+0.3–0.5%/day** after filters. → 10% in **~4–7 weeks**. No rush (unlimited time).
- **Phase 2 (target +5%):** *cut risk to `r = 0.25%`.* You only need half the gain and a
  fail here loses Phase 1 too — variance is now the enemy. Same strategies, smaller size.
- **Funded:** capital-preservation mode — `r = 0.2–0.3%`, daily profit-lock at +1%,
  prioritise *not breaching* over maximising (payouts come from consistency).

A dedicated `prop_ftmo_challenge` profile encodes Phase-1 numbers; switch profiles
between phases from **Settings** (the engine hot-reloads within ~10s).

---

## 6. Wiring it to the live limits

- Set `PropFirmParams` for FTMO: `daily_dd_limit_pct=5`, `total_dd_limit_pct=10`,
  `circuit_buffer_pct=1.0` (liquidate ~1% early), `daily_reset_hour=17`,
  `daily_reset_tz="Europe/Prague"` (FTMO's CE(S)T reset). Internally we run tighter
  governors (§4) so the breaker is rarely the thing that fires.
- **Overall loss for FTMO is from the static initial balance**, not a trailing peak —
  PropGuard's `total` should anchor to `starting_equity`, not the high-water mark, for
  this firm. (A trailing-peak firm like some others would keep the peak anchor.)
- Min-4-days: the system naturally spreads entries; we add a guard to not "rush" the
  target in <4 active days.

---

## 7. Validation gate (before any real challenge fee)

Run the Monte-Carlo backtester (next build, `apex/backtest/`) on **3–5y of real IG
data per instrument** and require, across all regimes **and** under 0.5–2pt slippage:

- P(pass Phase 1 without breach) ≥ **90%**, P(daily breach) ≤ **2%**, P(total breach) ≤ **1%**
- Profit Factor ≥ 1.3, expectancy > 0, max daily floating DD < 4%, max total floating DD < 8%
- Median time-to-target ≤ 8 weeks

Only a strategy that clears this distribution — not a single lucky backtest — is allowed
near a paid challenge. That harness is the immediate next deliverable.
