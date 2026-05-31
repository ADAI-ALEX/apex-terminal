# Apex Algo

> Production-grade automated spread betting system for **IG Markets UK**, with a real-time Next.js command-centre dashboard.

Apex Algo runs 24/5 against FTSE 100, US 500, DAX 40, EUR/USD and GBP/USD via IG spread bets.
**Python handles all order execution.** Claude (Anthropic API) acts as an advisory brain only — it
returns structured recommendations and *never* touches orders directly. Every order is forced
through a 9-rule `RiskEngine` before it can reach the broker.

---

## Architecture

```
                         ┌──────────────────────────────────────────┐
                         │              APEX ALGO (VPS)               │
                         │                                            │
   IG Lightstreamer ───► │  Heartbeat orchestrator (asyncio.gather)   │
   IG REST API     ◄───► │   • Tier 1  every 30s  price + SL/TP       │
                         │   • Tier 2  every  5m  signals + Claude     │
   Anthropic API  ◄───►  │   • Tier 3  every 30m  portfolio review     │
                         │   • Health  every  5m  watchdog            │
                         │                                            │
                         │  RiskEngine (9 circuit breakers)           │
                         │  SQLite trade journal                      │
                         │  FastAPI state server  :8080  /state /health│
                         └───────────────┬────────────────────────────┘
                                         │  GET /state  (X-Apex-Secret)
                                         ▼
                         ┌──────────────────────────────────────────┐
                         │         DASHBOARD (Vercel, Next.js)        │
                         │  /api/stream  SSE  ── polls VPS every 3s   │
                         │  NextAuth single-user JWT (8h sessions)    │
                         │  Overview · Live chart · Positions · Log   │
                         └──────────────────────────────────────────┘
```

Why **SSE not WebSockets**: Vercel serverless functions don't hold persistent socket
connections. The dashboard's `/api/stream` route polls the VPS state server every 3s and
streams updates to the browser — the standard production pattern.

---

## Project layout

```
spread-bet-algo/
├── main.py                  # Entry point — starts heartbeat + state server
├── apex/
│   ├── config.py            # ALL constants: markets, risk, strategy params
│   ├── models.py            # Typed domain models (pydantic)
│   ├── logging_setup.py     # loguru configuration
│   ├── ig/client.py         # IG REST/stream wrapper — the ONLY order path
│   ├── indicators/engine.py # EMA, RSI, MACD, ATR, Bollinger, ADX
│   ├── strategies/          # ema_trend, rsi_reversion, atr_breakout, regime
│   ├── risk/risk_engine.py  # 9 circuit breakers + ATR position sizing
│   ├── agents/              # Claude signal / portfolio / EOD agents
│   ├── journal/db.py        # SQLite trade journal
│   ├── core/                # shared state + heartbeat orchestrator
│   └── server/state_server.py  # FastAPI :8080 for the dashboard
├── tests/                   # pytest — indicators, risk engine, strategies
└── dashboard/               # Next.js 14 App Router + NextAuth + Tailwind
```

---

## Quick start (Windows)

```bat
start.bat
```

First run installs the Python venv, dashboard deps, and creates `.env` from the template.
Subsequent runs show a menu (DEMO/LIVE algo, dashboard, or both).

## Quick start (manual)

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
copy .env.example .env         # then fill it in
python main.py                 # starts algo + state server on :8080
```

Dashboard:

```bash
cd dashboard
npm install
cp .env.example .env.local     # set AUTH_SECRET, VPS_URL, VPS_SECRET, login creds
npm run dev                    # http://localhost:3000
```

---

## Safety model

- **DEMO by default.** `IG_ACC_TYPE=DEMO`. LIVE requires an explicit env flag *and* a typed confirmation in `start.bat`.
- **Kill switch.** `TRADING_ENABLED=false` blocks all order placement while everything else keeps running.
- **No naked orders.** `RiskEngine.evaluate_entry()` gates every entry; sizing is auto-reduced, never overridden upward.
- **AI never executes.** Claude returns JSON recommendations. On any Claude error/timeout the system falls back to `NO_TRADE`.
- **No secrets in code.** Everything sensitive lives in `.env` / Vercel env vars.

> ⚠️ Spread betting carries significant risk of loss. This software is provided for educational
> purposes. Test thoroughly on a DEMO account. You are responsible for any LIVE trading.

---

## Configuration

All tunable constants live in [`apex/config.py`](apex/config.py): market EPICs, risk thresholds,
strategy parameters, heartbeat intervals. No magic numbers in logic files. See
[`MASTER_PLAN.md`](MASTER_PLAN.md) for the full design rationale.
