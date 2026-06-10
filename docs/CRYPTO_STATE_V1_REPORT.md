# Crypto State V1 — Phase-5 Final Report

**Mandate.** Pivot from US500 intraday (proven zero-expectancy on 15M after costs) to
BTC/ETH perpetual futures; build a 15M state-transition engine targeting >3–5%/month
inside FTMO constraints (internal ceilings: 4% daily DD, 9% total DD); costs ON; iterate
autonomously until convergence **or until the mathematical boundary of the data is mapped**.

**Verdict in one paragraph.** The structural thesis is *half right*. Crypto perps on 15M
carry a real, large, cross-replicated inefficiency — but it is **long-only momentum
continuation conditioned on macro regime**, not the regime-agnostic high-frequency
scalping hypothesized. Fully exploited and risk-bounded, it yields **≈0.6%/month
averaged over all climates (2020-2026)** — matching the 1H equity champion V5.2's yield
with materially better risk (PF 1.70 vs 1.30, total DD 7.6% vs 9.4%, MC pass 83.7% vs
66.3%) — and **+0.9 to +7.6%/month inside permitted regimes**, while sitting 100% flat
through all four secular-bear half-years. The >3%/month *every-month* target is **not
achievable robustly on this data at real costs**; the binding constraints are mapped below.

---

## 1. Data infrastructure (new)

`scripts/seed_binance_perp.py` — Binance USDT-M perp archive (no key needed):

| Series | Bars | Span | New columns |
|---|---|---|---|
| BTC/ETH 1h | 56,232 | 2020-01 → 2026-05 | `delta` (real taker buy−sell flow), `macro` (% vs 50-day daily SMA), `macro_slow` (% vs 200-day) |
| BTC/ETH 15m | 224,928 | 2020-01 → 2026-05 | same |
| BTC/ETH 5m | 359,136 | 2023-01 → 2026-05 | same |
| BTC/ETH 1m | 743,040 | 2025-01 → 2026-05 | same (local-only, gitignored) |

Macro overlays are computed from **completed daily closes only** (walk-forward,
live-reproducible). Engine now supports `cost_pct` (percent-of-notional round-trip
costs — correct across BTC's 9k→120k span). All tests at **0.12% RT** (≈ taker fee +
slippage both sides); robustness re-tested at **0.18%**.

New snippet primitives: `hmm()` (walk-forward Gaussian HMM: Baum-Welch refit cadence +
incremental forward filter), `flow(n)` / `flow_norm(n)` (real taker-flow pressure),
`delta`, `macro`, `macro_slow`.

## 2. Probe findings (BTC 15m, 6.4y; ETH replicates) — `scripts/dev_crypto_probe.py`

| Conditional state | Fwd return | t-stat | Conclusion |
|---|---|---|---|
| past-24h ret > +1σ → next 24h | +10.0 bps | 10.7 | momentum continues (long side) |
| past-24h ret < −1σ → next 24h (short) | −1.0 bps | −0.9 | **shorts do not pay** |
| down-breakouts in bear regime (short, 4h) | bounce +12 bps | 3.3 | shorts get squeezed |
| top taker-flow quintile → 2h | +3.4 bps | 8.4 | real flow confirms |
| vol contraction → fwd \|move\| | **less** movement | — | squeeze-breakout thesis dead |
| down-cascade fade → 6h | −6.7 bps | −1.9 | cascade-fading dead |
| mom96 ∧ mom24 ∧ flow>0.03 → 24h | **+52.6 bps** | **14.6** | the tradable state |
| …above 50-day daily SMA | +52.6 bps | 19.8 | **the entire edge lives here** |
| …below 50-day daily SMA | −8.7 bps | −2.4 | bear rallies are a trap |

Cost hurdle: 12 bps RT. The intersected state clears it 4×.

## 3. R&D loop (20 iterations, all archived in `scripts/dev_crypto_state.py`)

Key transitions (mean %/month across contrasting climate windows, BTC 15m, costs on):

| Iter | Change | Mean ret/mo | Lesson |
|---|---|---|---|
| base_mk | US500 champion logic ported | −1.10 | mean-reversion dies on crypto 15M |
| c1–c4 | momentum + HMM gates, state-presence entries | −0.6..−0.2 | re-entry churn ≈ linear loss in trade count |
| c5–c6 | explicit momentum-z hysteresis + 4-day SMA | **+0.13** | deep hysteresis beats trails/time exits |
| c7–c9 | extension-chasing / trails / caps | −0.6..−0.3 | never cap the fat tail; trails churn on 15M |
| c11–c13 | `macro` (50-day) overlay | +0.10 | regime ≠ timing; both gates needed |
| c15 | + `macro_slow` (200-day) dual-momentum | +0.38 | **bear windows: zero trades** |
| c15x | **HMM gate ablated** | +0.66 | HMM directional gating *subtracts* (−0.3/mo) |
| c16 | graduated streak/DD risk curve | +0.58 | 7-loss streak now costs 4.5%, not the halt |
| c18 | fresh-high (Turtle) gate | +0.26 | fixes chop, amputates early-trend → rejected |
| c19/c20 | stop floor 2.2% + daily lock −2% | **+0.60** | ships as `crypto_state_v1.py` |
| c20s | risk 1.1→1.6% | +0.70 | **breaches 4% daily ceiling — concave, rejected** |

## 4. Benchmark matrix (identical engine, halts, MC: +10% target before −9% stop)

| Engine | Market/TF | Span | Trades | Win% | PF | Ret/mo | Max daily DD | Max total DD | MC pass |
|---|---|---|---|---|---|---|---|---|---|
| **Crypto State V1** | BTC 15m | 77 mo | 143 | 35.0 | **1.70** | **0.59%** | **2.86%** | **7.57%** | **83.7%** |
| **Crypto State V1** | ETH 15m | 77 mo | 197 | 40.1 | 1.34 | 0.34% | 2.39% | 7.59% | 69.0% |
| Crypto V1 @1.5× costs | BTC 15m | 77 mo | 140 | 35.7 | 1.63 | 0.51% | 2.92% | 7.65% | 81.0% |
| Crypto V1 @1.5× costs | ETH 15m | 77 mo | 196 | 39.3 | 1.28 | 0.26% | 2.41% | 7.53% | 65.7% |
| V5.2 champion (baseline) | US500 1h | 41 mo | 103 | 56.3 | 1.30 | 0.61% | 3.88% | **9.44%** | 66.3% |
| Ported V5.2-class MR | BTC 15m | dev | — | — | 0.3-0.5 | −1.10% | — | — | 0% |

In-regime performance (the 9 half-years the gates permitted trading, BTC): mean
**+0.87%/mo**, best +5.87%/mo (2020H2), worst −1.17%/mo (2023H2, the documented
chop failure-mode, bounded by the halt stack). Four bear half-years: **0 trades, 0 loss.**

## 5. Boundary mapping — why not 3–5%/month

1. **Capture ceiling.** The richest state (≈7% of bars) drifts ≈+50 bps/24h. Perfect
   capture at the ~1× notional implied by risk-per-trade sizing ≈ **1.1%/month**.
   Realized 0.6%/mo is near that ceiling after costs and stop truncation.
2. **Risk scaling is concave.** 1.6% base risk adds only +0.10%/mo and breaches the 4%
   daily ceiling (throttles bind before yield does). The 9% runway cannot be "occupied"
   further without becoming the 2023H2 tail.
3. **Shorts are structurally unprofitable** on both symbols (squeeze asymmetry) —
   halving the opportunity set vs an equity-style two-sided engine.
4. **Frequency.** Surviving costs requires selectivity (~2.5 trades/mo in-regime);
   every relaxation tested (c17) lowered returns. "High-frequency 15M" and "cost-robust
   edge" are mutually exclusive on this data.

What ≈3%/mo *would* require (documented, untested beyond this engine's scope):
regime-conditional capital rotation (run this engine only in permitted regimes and
deploy elsewhere otherwise), pyramiding inside extended states (engine unsupported),
or accepting challenge-grade gambles the mandate's ceilings forbid.

## 6. Negative results (preserved so they are never re-tested)

- Gaussian-HMM **directional gating** reduces returns vs observable macro/momentum/flow
  states (ablation-proven, both symbols). HMM remains available as `hmm()` for
  volatility-state research.
- Mean-reversion architectures, cascade fades, vol-contraction breakouts, short-side
  momentum, ATR trails on 15M, extension caps: all dead on this data.

## 7. Deployment recommendation

Run `crypto_state_v1.py` on **BTCUSD and ETHUSD simultaneously at ~0.6× risk each**
(worst windows anti-correlate: ETH was +0.69%/mo in BTC's worst half-year). Expected
blended: ≈0.6–0.8%/mo all-climate, 1–3%/mo in permitted regimes, with double-layer
halts far inside FTMO limits. This is a **second uncorrelated book** alongside V5.2 —
not a replacement for it.
