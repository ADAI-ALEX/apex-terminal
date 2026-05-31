# CLAUDE.md — Apex Algo project context

## What This Is
Apex Algo is a production-grade automated spread betting system for IG Markets UK.
It runs 24/5, trades FTSE 100, US 500, DAX 40, EUR/USD, GBP/USD via spread bets.
The brain is the Claude API (claude-sonnet-4-6) for signal evaluation.
Python handles ALL order execution — Claude NEVER touches orders directly.

## Stack
- Backend: Python 3.11+ with asyncio, trading-ig library
- Indicators: pure-Python engine (no pandas dependency) in `apex/indicators/engine.py`
- Dashboard: Next.js 14 App Router, TypeScript, Tailwind CSS
- Charts: TradingView Lightweight Charts v4
- Auth: NextAuth.js v5 (single user, credentials provider, JWT sessions)
- Realtime: Server-Sent Events (SSE) — Next.js `/api/stream` polls the VPS state server
- State server: FastAPI on the VPS (`apex/server/state_server.py`, port 8080)
- Database: SQLite trade journal (`apex/journal/db.py`)
- Deployment: Python algo on VPS, dashboard on Vercel

## Layout
- `main.py` — entry point (heartbeat + state server via asyncio)
- `apex/config.py` — ALL constants (markets, risk, strategy, heartbeat)
- `apex/core/heartbeat.py` — 3-tier async orchestrator
- `apex/risk/risk_engine.py` — 9 circuit breakers + ATR sizing
- `apex/strategies/` — ema_trend, rsi_reversion, atr_breakout, regime
- `apex/agents/` — Claude signal / portfolio / EOD agents
- `dashboard/` — Next.js app
- `tests/` — pytest (30 passing)

## Hard Rules
- NEVER hardcode credentials. All secrets in `.env` files.
- NEVER bypass RiskEngine. Every entry goes through `apex/risk/risk_engine.py` first.
- ALL Python files: fully typed, loguru logging, docstrings on functions.
- ALL Next.js files: TypeScript strict mode, no `any` types where avoidable.
- IG DEMO account for all development. Falls back to PaperBroker with no credentials.
- `config.py` owns ALL constants. No magic numbers in logic files.
- Claude failures ALWAYS fall back to NO_TRADE — never crash the trading loop.

## Current Phase
v1 scaffold complete — full Python algo + dashboard built, 30 tests passing,
paper-trading path verified. Next: wire a macro calendar (news blackout), broker
stop-amend for trailing stops, and the Performance/Trade-Log dashboard pages.
