# Apex Algo — Complete Master Plan v2

> ADAI Systems · IG Spread Bet UK · Python algo on VPS + Next.js dashboard on Vercel.
> This is the design source-of-truth. Implementation lives in `apex/` and `dashboard/`.

---

## 01 — Strategies + regime gating

| Strategy | Signal logic | Win rate | R:R | Best regime | TF |
|---|---|---|---|---|---|
| **EMA Trend Confluence** | EMA9 > EMA21 > EMA55 + MACD rising + RSI 45–70 | 48–55% | 1.6:1 | TRENDING | 15m |
| **RSI Mean Reversion** | RSI crosses 30 up + near lower Bollinger + ATR active | 62–68% | 1.1:1 | RANGING | 5m |
| **ATR Breakout** | 3+ candles ATR compression then range break + sentiment | 52–58% | 2.5:1 | ALL | 30m |

A **Regime Detector** (ADX + ATR rate-of-change) classifies the market as
`TRENDING / RANGING / VOLATILE` every 5 minutes and gates which strategy has authority.
Claude agents may override the classification on macro context (e.g. pre-FOMC = no new positions).

## 02 — Markets & IG EPIC codes (spread bet DFB)

| Market | IG EPIC | Spread | FCA leverage | UK hours |
|---|---|---|---|---|
| FTSE 100 | `IX.D.FTSE.DAILY.IP` | 1pt | 20:1 | 08:00–16:30 |
| US 500 (S&P) | `IX.D.SPTRD.DAILY.IP` | 0.4pt | 20:1 | 14:30–21:00 |
| Germany 40 (DAX) | `IX.D.DAX.DAILY.IP` | 1pt | 20:1 | 08:00–16:30 |
| EUR/USD | `CS.D.EURUSD.MINI.IP` | 0.8pt | 30:1 | 07:00–17:00 |
| GBP/USD | `CS.D.GBPUSD.MINI.IP` | 0.9pt | 30:1 | 07:00–17:00 |

> Always verify EPICs via `GET /markets?searchTerm=FTSE` after authenticating. `.IP` = IG Index
> (spread bet). Do **not** use `.CFD.IP` variants.

## 03 — Position sizing / leverage

- **2%** max risk per trade · **5:1** max effective leverage · **6%** max total open risk.
- Stake (£/pt) = `risk_amount_GBP / (ATR14 × stop_multiplier)`.
- Hard floor **£0.50/pt** (IG minimum). Hard ceiling: never risk >5% of account on one position.
- ATR-based sizing ⇒ smaller stakes in volatile conditions, larger in calm.

## 04 — The heartbeat system (three async tiers via `asyncio.gather`)

| Tier | Cadence | Responsibility |
|---|---|---|
| **Tier 1** | 30s | Price monitoring + SL/TP enforcement. Pure Python, no Claude. Fires close orders immediately on hit. |
| **Tier 2** | 5m | Build candle, run 3 strategies, classify regime. Pre-screened signals go to Claude Signal Evaluator → approved trades execute. |
| **Tier 3** | 30m | Portfolio review + macro scan. Claude Portfolio Reviewer → early-exit / stop-trail recommendations. |
| **Health** | 5m | Watchdog: logs alive + position count + daily P&L + API counts; writes shared state for the dashboard. |

Each tier is isolated — a failure in one never crashes another.

## 05 — Claude agent roles

- **Signal Evaluator** (Tier 2): per-signal. Receives indicator snapshot + regime + open positions + macro calendar → JSON `ENTER | NO_TRADE` with confidence + reasoning.
- **Portfolio Reviewer** (Tier 3): reviews open positions vs events/funding/correlation → close-early / trail-stop / health score.
- **EOD Analyst** (post-market 18:00): full journal → structured debrief, parameter flags, day score.

> **Rule:** Claude recommends, Python executes. Claude failure ⇒ `NO_TRADE`. The system never crashes on an AI timeout.

## 06 — Risk engine: 9 circuit breakers

| Rule | Threshold | Action |
|---|---|---|
| Daily loss limit | −5% account | Block new entries until next day |
| Weekly loss limit | −10% account | Full halt — manual restart + alert |
| Max concurrent positions | 3 open | Block new signals |
| Single trade risk | >2% account | Auto-reduce bet size (never override up) |
| Total open risk | >6% account | Block new entries until risk reduces |
| Consecutive losses | 4 in a row | 50% bet size for next 10 trades |
| News blackout | 30m before major event | Block new entries; monitor open |
| Overnight hold | 22:00 UK | Close positions with <20pt profit target |
| Market close buffer | 15m before close | Close all positions in that instrument |

## 07 — Web dashboard (Next.js 14 → Vercel)

Pages: **Overview · Live Chart · Positions · Trade Log · Performance · System Log**.
Charts via **TradingView Lightweight Charts v4**. Realtime via **SSE** (Vercel has no persistent
WebSockets): Python writes state → FastAPI `:8080 /state` → Next.js `/api/stream` polls every 3s →
browser. State server protected by a shared `X-Apex-Secret` header.

## 08 — Auth (single-user JWT)

NextAuth v5 Credentials provider, stateless JWT, 8h sessions. `DASHBOARD_USERNAME` +
`DASHBOARD_PASSWORD_HASH` (bcrypt) + `AUTH_SECRET` in Vercel env. Middleware protects every route
except `/login` and `/api/auth`.

## 09 — `start.bat`

One-click Windows setup + launch menu (DEMO / LIVE algo, dashboard, or both). First run installs
the venv + dashboard deps + creates `.env`. LIVE mode requires typing `CONFIRM`.

## 10 — File architecture

See `README.md` → "Project layout".

## 11 — Claude Code build configuration

- **Opus** for architecture-critical phases: risk engine, Claude agent prompts, auth middleware.
- **Sonnet** for well-defined implementation: IG client, indicators, strategy logic, journal, tests.
- Effort: `xhigh` default; **Max** for the risk engine and agent prompt files.
- Keep `CLAUDE.md` "Current Phase" line updated each session.
