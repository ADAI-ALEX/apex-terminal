# Apex Algo

> An interactive, browser-based trading terminal with a live algorithm builder, an
> offline backtester, and a strategy comparison lab — backed by a Python execution
> engine for IG Markets (spread bets) and FTMO/MT5 (prop trading).

Apex Algo is **not** a single fixed trading bot. It's a terminal: a dockable-widget
dashboard for monitoring a live account, plus an "Algorithms" workspace where you
write trading strategies in an in-browser code editor, backtest them against 20 years
of local offline data (no network calls), and compare multiple strategies side-by-side
on equity curves, drawdown, win rate, profit factor, expectancy and a Monte-Carlo
prop-challenge pass probability. Whatever you build can then be promoted to the live
strategy book, which the execution engine trades 24/5 under a hard risk-engine gate.

Claude (Anthropic API) is used as an **advisory** brain — it evaluates signals and
reviews the portfolio, returning structured JSON recommendations. It never places
orders. **Python executes every order**, and every entry is forced through a
multi-rule `RiskEngine` (plus a prop-firm floating-equity breaker) before it can
reach the broker.

> This public repo ships with the terminal app and one demo strategy ("Auction Flow").
> The full strategy research library used on the author's live/prop accounts is kept
> private and is not included here.

---

## What you can do with it

- **Live terminal** — a dockable, resizable widget grid: price chart, watchlist,
  account stats, open positions, P&L calendar, risk/circuit-breaker panel,
  indicators, AI usage/cost tracker, calculator, and system log.
- **Algorithms workspace** — build a strategy in a small Python-like per-bar DSL
  (`sma`, `ema`, `rsi`, `macd`, `atr`, `bollinger`, `adx`, `vwap`, `volume_profile`,
  `cvd`, `markov`, session/hour filters, …), save it, and it shows up instantly as a
  selectable strategy.
- **Backtesting** — replay any strategy (built-in book or your own) over offline
  multi-year local datasets across several instruments and timeframes (daily down to
  5m), or against live-fetched data. Replay is intrabar (stops/targets checked
  against each candle's high/low) and floating equity is marked every bar — the same
  way a prop-firm auditor measures drawdown.
- **Compare** — run several strategies over the same window and overlay their
  equity curves, with full trade logs and a Monte-Carlo bootstrap of breach
  probability for prop-challenge style drawdown limits.
- **Go live** — promote a strategy into the live multi-strategy book; the heartbeat
  orchestrator trades it under the same risk engine used in backtesting.

---

## Architecture

```
                         ┌──────────────────────────────────────────┐
                         │           APEX ALGO ENGINE (VPS)           │
                         │                                            │
   IG / MT5 bridge ───►  │  Heartbeat orchestrator (asyncio.gather)   │
   IG REST API     ◄───► │   • Tier 1  every 30s  price + SL/TP       │
                         │   • Tier 2  every  5m  signals + Claude     │
   Anthropic API  ◄───►  │   • Tier 3  every 30m  portfolio review     │
                         │   • Health  every  5m  watchdog            │
                         │                                            │
                         │  RiskEngine (circuit breakers) + PropGuard │
                         │  Backtest engine (offline + live data)     │
                         │  SQLite trade journal                      │
                         │  FastAPI state server  :8080  /state /health│
                         └───────────────┬────────────────────────────┘
                                         │  GET /state  (X-Apex-Secret)
                                         ▼
                         ┌──────────────────────────────────────────┐
                         │      TERMINAL (Next.js, Vercel or local)   │
                         │  /api/stream  SSE  ── polls the engine     │
                         │  NextAuth single-user JWT (8h sessions)    │
                         │  Terminal tab: dockable widget grid        │
                         │  Algorithms tab: editor · backtest · compare│
                         └──────────────────────────────────────────┘
```

Why **SSE not WebSockets**: serverless functions (e.g. on Vercel) don't hold
persistent socket connections. The terminal's `/api/stream` route polls the engine's
state server every 3s and streams updates to the browser.

The app **launches unconfigured** — open it, complete the onboarding wizard
(broker + Claude keys, risk profile), and only then does the live trading heartbeat
start. The Algorithms/backtest workspace works immediately, with or without live
credentials, since it runs entirely on local data.

---

## Project layout

```
apex-terminal/
├── main.py                     # Entry point — state server + onboarding-gated heartbeat
├── apex/
│   ├── config.py                # ALL constants: markets, risk, strategy params
│   ├── models.py                # Typed domain models (pydantic)
│   ├── ig/client.py              # IG REST/stream wrapper — the live order path
│   ├── indicators/engine.py     # Pure-Python indicator engine (SMA/EMA/RSI/MACD/ATR/...)
│   ├── strategies/
│   │   ├── ema_trend.py, rsi_reversion.py, atr_breakout.py, regime.py
│   │   ├── store.py              # Scans + saves user-authored strategies
│   │   └── custom/                # Strategies built in the Algorithms editor
│   ├── backtest/                 # Backtest engine, offline dataset loader, runner
│   ├── risk/risk_engine.py       # Circuit breakers + ATR position sizing
│   ├── risk/prop_guard.py        # Prop-firm floating-equity breaker
│   ├── agents/                   # Claude signal / portfolio / EOD agents
│   ├── onboarding/                # Encrypted-at-rest setup store + wizard API
│   ├── journal/db.py              # SQLite trade journal
│   ├── core/                      # Shared state + heartbeat orchestrator
│   └── server/state_server.py    # FastAPI :8080 — serves terminal + onboarding API
├── tests/                        # pytest
└── dashboard/                    # Next.js 14 App Router terminal (Terminal + Algorithms tabs)
```

---

## Quick start (Windows)

```bat
start.bat
```

First run installs the Python venv, dashboard deps, and creates `.env` from the
template. Subsequent runs show a menu (DEMO/LIVE engine, terminal, or both).

## Quick start (manual)

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
copy .env.example .env         # then fill it in (optional — onboarding wizard can do this too)
python main.py                 # starts the engine + state server on :8080
```

Terminal:

```bash
cd dashboard
npm install
cp .env.example .env.local     # set AUTH_SECRET, VPS_URL, VPS_SECRET, login creds
npm run dev                    # http://localhost:3000
```

Open the terminal, finish onboarding (or skip straight to the **Algorithms** tab to
backtest — no broker credentials required for that).

---

## Safety model

- **DEMO by default.** Live trading requires an explicit env flag *and* a typed
  confirmation in `start.bat`.
- **Kill switch.** `TRADING_ENABLED=false` blocks all order placement while
  everything else keeps running.
- **No naked orders.** `RiskEngine.evaluate_entry()` gates every entry; sizing is
  auto-reduced, never overridden upward. Prop accounts add `PropGuard` as an
  account-level floating-drawdown backstop.
- **AI never executes.** Claude returns JSON recommendations. On any Claude
  error/timeout the system falls back to `NO_TRADE`.
- **No secrets in code.** Everything sensitive lives in `.env` / the encrypted
  onboarding store — never committed.

> ⚠️ Spread betting and leveraged trading carry significant risk of loss. This
> software is provided for educational purposes. Test thoroughly on a DEMO account
> and in the backtester before risking real capital.

---

## Configuration

All tunable constants live in [`apex/config.py`](apex/config.py): market EPICs, risk
thresholds, strategy parameters, heartbeat intervals. No magic numbers in logic
files. See [`docs/PROP_FIRM_PLAN.md`](docs/PROP_FIRM_PLAN.md) for the prop-firm
research and roadmap behind the risk model.
