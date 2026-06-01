# Apex Algo — Prop-Firm Research & 4-Phase Roadmap

> Quant-research source-of-truth for taking the Claude-brain engine onto a retail
> prop-firm account (FTMO / The5ers style) at $100k+. Pairs with `MASTER_PLAN.md`
> (system design) and `CLAUDE.md` (project rules).
>
> **Objective:** average **+0.5%/day** (~10%/month) with **hard** guardrails —
> max **daily** equity drawdown **< 3%**, max **total** drawdown **< 8%**, measured
> on *floating* equity (open + closed), the way a prop auditor measures it.

---

## STEP 1 — Instrument selection

We scored the three candidates on the four properties that actually decide whether a
0.5%/day target survives a 3% daily floating-DD filter: **predictable daily ATR**,
**cost-to-ATR ratio**, **gap / slippage risk**, and **liquidity depth** (which
governs how closely live fills track the backtest — the single biggest risk to a
prop audit).

| Metric (typical 2021–2025) | **US 500** (S&P) | **NAS 100** | **EUR/USD** |
|---|---|---|---|
| Daily ATR (% of price) | ~0.8–1.2% | ~1.2–1.8% | ~0.4–0.6% |
| Spread / transaction cost | ~0.4 pt (~0.01%) | ~1–2 pt (~0.01%, widens fast) | ~0.1–0.6 pip (lowest) |
| Overnight gap risk | Moderate | **High** (tech earnings, AH moves) | Low (24/5 continuous) |
| Tail / event sensitivity | Moderate | **High** (CPI/FOMC fat tails) | Moderate (CB-driven spikes) |
| Liquidity depth → fill quality | **Deepest** | Deep | Deepest (FX) |
| Backtest→live slippage gap | **Smallest** | Largest | Small |

### Verdict

- **US 500 — PRIMARY engine.** ATR is *high enough* that a 1:1.8 trade risking
  0.3–0.5% of equity can realistically capture a 0.6–1.0% intraday swing, yet *not
  so volatile* that stops get whipsawed or gapped through. Deepest liquidity ⇒
  smallest backtest-to-live divergence ⇒ the audit you pass in simulation is the
  one you pass live. This is the best ATR-vs-tail-risk balance of the three.
- **EUR/USD — SECONDARY diversifier (half weight).** Tightest costs and lowest
  single-name idiosyncratic risk, but its low ATR forces tighter stops / higher
  leverage to reach 0.5%/day, which invites noise stop-outs. Best as a
  low-correlation satellite that smooths the equity curve, not the main driver.
- **NAS 100 — OPTIONAL satellite, reduced size only.** It can hit targets fastest,
  but its fat tails and overnight gaps make a *hard* 3% daily stop fragile: a single
  CPI/FOMC candle can gap straight through a resting stop. Enabled only at half risk
  and never held into tier-1 macro prints.

> **Why ATR predictability beats raw volatility:** the prop constraint is not "make
> the most" — it's "never have one bad day." An instrument whose daily range is
> *stable and continuous* lets the position-sizer convert a fixed % risk into a
> reliable point-distance. NAS100's variance of variance is the enemy of a fixed
> daily-loss filter.

---

## STEP 1.3 — The risk-reward math (how 0.5%/day coexists with a 3% daily stop)

The core insight: **position sizing is the primary drawdown control; the circuit
breaker is only the backstop.** We size so small that a realistic losing streak
*cannot* reach the breaker, then let the breaker catch the pathological case.

Definitions — per-trade risk `r` (% of equity), win rate `W`, reward:risk `R`,
trades/day `N`. Expectancy per trade in units of `r`:

```
E = W·R − (1 − W)
DailyReturn ≈ N · r · E
```

Strategy book (from `MASTER_PLAN.md` §01, prop-tuned):

| Strategy | W | R | Expectancy `E` (×r) |
|---|---|---|---|
| EMA Trend Confluence | 0.50 | 1.8 | **+0.40** |
| RSI Mean Reversion | 0.64 | 1.1 | **+0.34** |
| ATR Breakout | 0.55 | 2.5 | **+0.93** |
| **Blended** | — | — | **≈ +0.45** |

**Choose `r = 0.4%` per trade.** To net +0.5%/day:

```
N = 0.5% / (0.4% × 0.45) ≈ 2.8 winning-equivalent trades
  → ~3–5 quality signals/day across US500 + EUR/USD on 5–15m.  ✅ realistic
```

**Why a bad day stays under 3%:**

- `r = 0.4%` ⇒ it takes ~**6 consecutive full-risk losses** to reach −2.4%.
- The **consecutive-loss throttle** halves size after 4 losses (`config.py`
  `consecutive_loss_*`), so loss #5–6 risk only 0.2% each.
- **Max 3 concurrent positions** caps simultaneous floating risk at ≈ **1.2%**.
- The **PropGuard circuit breaker** liquidates everything at **−2.5% floating**
  (0.5% buffer before the 3% hard limit, exactly per Step 4), and locks until the
  daily reset.

Net: the structure makes a >3% day a near-impossibility short of a catastrophic
gap — and gap exposure is itself minimised by instrument choice and the macro
blackout. Expected daily outcome distribution ≈ **−1.5% (rare bad) → +1.5% (good)**,
centred on **+0.5%**.

> **Prop translation:** at $100k, `r = 0.4%` = **$400 risk/trade**, daily breaker at
> **−$2,500**, total breaker at **−$8,000** off the high-water peak. These map
> directly onto FTMO ($5k daily / $10k total on a $100k 2-step) with margin to spare.

---

## STEP 2 — The 4-phase roadmap

### Phase 1 — Rigorous backtesting (validation)  ·  `apex/backtest/`
- **Data:** pull historical candles from IG REST
  `GET /prices/{epic}` (`fetch_historical_prices_by_epic`) at 1m/5m/15m. IG caps
  history per request, so the loader **pages backward** by date window and caches to
  `data/history/{epic}/{resolution}.parquet`. 3–5y of 5m needs paging + a free
  fallback source (Stooq/Dukascopy) for the deep tail.
- **Engine:** event-driven, **intrabar** replay (not close-to-close) so stops/targets
  and **floating equity** are evaluated at the high/low of each bar — this is what
  reproduces a prop auditor's tick-level DD.
- **Floating-equity DD tracker:** records peak-to-trough of *open* P&L continuously,
  not just on closed trades. Emits both **relative** (% of peak) and **absolute** (£).
- **Shock coverage:** must survive 2018-Q4, COVID-2020, 2022 rate shock, 2023 SVB,
  2024–25 — i.e. ≥3 distinct volatility regimes.
- **Gate to Phase 2:** Profit Factor ≥ 1.3, max daily floating DD < 3%, max total
  floating DD < 8%, expectancy > 0, across all regimes *and* under slippage stress.

### Phase 2 — Live paper trading (IG **Demo** API)  ·  current stack
- Onboard the **Demo** account through the Web UI (Step 3 below) — no terminal env edits.
- **Lightstreamer** streaming for tick prices + trade confirmations (real-time, not
  polled). Falls back to REST polling if the stream drops.
- Run **hands-off** and assert live daily DD / slippage / fill latency match the
  backtest within tolerance. Divergence here = a modelling bug to fix before real money.

### Phase 3 — Small-scale live (IG **real money**)
- Flip the same UI config from `DEMO` → `LIVE` (re-validates the IG session).
- Small personal capital. Verify spread-widening on news, real execution latency,
  and that **hard stops ride inside the order payload** (already true in
  `IGBroker.open_position`: `stop_level` is sent with the order, never held in memory).
- Watch for partial fills / requotes that paper mode can't show.

### Phase 4 — The prop-firm bridge  ·  `apex/execution/` (new Execution Module)
- **Signal stays in the core**; only the Execution Module changes — that is exactly
  what the `Broker` Protocol decoupling in `apex/ig/client.py` was built for.
- **Option A — MT5 (`MetaTrader5` Python lib):** core engine pushes orders into a
  local MT5 terminal logged into the prop account. Lowest-latency, native SL/TP.
- **Option B — ZeroMQ / socket bridge:** core publishes JSON execution commands on a
  ZMQ `PUSH` socket; a lightweight MT5 Expert Advisor (or cTrader FIX client)
  `PULL`s and executes. Language-agnostic, survives terminal restarts.
- **VPS + fail-safes:** runs 100% hands-off on a VPS. A **dead-man's switch**
  auto-flattens all positions if the heartbeat to the broker/bridge is lost for
  > N seconds (PropGuard already owns the "lock + liquidate" primitive).

---

## STEP 5 — Broker integration & streaming specs

| Layer | Protocol | Where |
|---|---|---|
| Historical data, auth, account health, **onboarding validation** | IG **REST** | `apex/ig/client.py`, `apex/onboarding/validator.py` |
| Live tick prices + trade confirmations | IG **Lightstreamer** | `apex/ig/stream.py` (Phase 2) |
| Prop execution | **MT5** lib *or* **ZeroMQ→EA / cTrader FIX** | `apex/execution/` (Phase 4) |

**Hard-stop rule (non-negotiable):** every entry submits its stop *in the same order
payload* (REST `create_open_position` `stop_level`, MT5 `sl=` field). Stealth/in-memory
stops are prohibited so a process crash or dropped connection can never leave a
naked position.

---

## STEP 6 — Backtest report metrics (what `apex/backtest/report.py` emits)

- **Max relative & absolute floating-equity drawdown** (peak-to-trough of *open* P&L).
- **Profit Factor** = gross profit ÷ gross loss.
- **Win rate** paired with **average realised R:R**.
- **Expectancy** per trade (£ and ×r).
- **Slippage-stress variance:** re-run with 0.5–2.0 pt of random latency slippage
  injected per fill; report how PF / DD / expectancy degrade. A strategy that only
  works at zero slippage is rejected.
- Plus: Sharpe/Sortino, max consecutive losses, exposure %, trades/day distribution.

---

## STEP 3/4 implementation status (this build)

- ✅ **Unconfigured Web-UI onboarding state** — `apex/onboarding/` + dashboard
  `OnboardingGate`/`OnboardingWizard`. App launches with **zero** credentials; IG +
  Claude keys + risk profile are entered and validated in the UI; trading modules
  stay locked until onboarding completes. Secrets persist **encrypted at rest**
  (Fernet) — never in plaintext, never committed.
- ✅ **Prop-firm RiskEngine safeties** — `apex/risk/prop_guard.py`: 1-second floating
  equity tracker, daily reset at the configured prop time, circuit breaker that
  liquidates + locks at 0.5% before the limit, concurrency/size caps, hard-stop
  injection (in the IG order payload).
- ⏳ **Phase 1 backtester / Phase 4 bridge** — specified above; modules scaffolded
  next per this roadmap.
