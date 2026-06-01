# CLAUDE.md — Apex Algo project context

## What This Is
Apex Algo is a production-grade automated spread betting system for IG Markets UK,
on a path to a retail prop-firm account (FTMO/The5ers) at $100k+. Target +0.5%/day
with hard guardrails: daily floating drawdown < 3%, total < 8% (see
`docs/PROP_FIRM_PLAN.md`). It runs 24/5, trades US 500 (primary), EUR/USD, NAS 100,
FTSE 100, DAX 40, GBP/USD via spread bets. The brain is the Claude API
(claude-sonnet-4-6) for signal evaluation. Python handles ALL order execution —
Claude NEVER touches orders directly.

The system **launches unconfigured**: open the dashboard, complete the onboarding
wizard (IG + Claude keys, risk profile), and only then does the trading heartbeat
start. No terminal env editing required.

## Stack
- Backend: Python 3.11+ with asyncio, trading-ig library
- Indicators: pure-Python engine (no pandas dependency) in `apex/indicators/engine.py`
- Dashboard: Next.js 14 App Router, TypeScript, Tailwind CSS
- Charts: TradingView Lightweight Charts v4
- Auth: NextAuth.js v5 (single user, credentials provider, JWT sessions)
- Realtime: Server-Sent Events (SSE) — Next.js `/api/stream` polls the VPS state server
- State server: FastAPI on the VPS (`apex/server/state_server.py`, port 8080) —
  also serves the onboarding API (`/onboarding/status|validate|save|reset`)
- Onboarding: encrypted-at-rest store (`apex/onboarding/`, Fernet) written by the UI
- Database: SQLite trade journal (`apex/journal/db.py`)
- Deployment: Python algo on VPS, dashboard on Vercel

## Layout
- `main.py` — entry point: state server always up; heartbeat gated behind onboarding
- `apex/config.py` — ALL constants + RISK_PROFILES (ig_standard | prop_ftmo) + env/store overlay
- `apex/core/heartbeat.py` — 3-tier async orchestrator (+ Tier-1 prop circuit-breaker check)
- `apex/risk/risk_engine.py` — 9 entry circuit breakers + ATR sizing
- `apex/risk/prop_guard.py` — prop-firm floating-equity breaker (liquidate + lock)
- `apex/onboarding/` — store (encrypted), schema, validator, service, runtime signal
- `apex/strategies/` — ema_trend, rsi_reversion, atr_breakout, regime
- `apex/agents/` — Claude signal / portfolio / EOD agents
- `dashboard/` — Next.js app (`OnboardingGate` + `OnboardingWizard` lock the UI until configured)
- `docs/PROP_FIRM_PLAN.md` — quant research, instrument selection, 4-phase roadmap
- `tests/` — pytest (42+ passing)

## Hard Rules
- NEVER hardcode credentials. Secrets live in `.env` (VPS/CI) OR the encrypted
  onboarding store (`~/.apex/runtime.json.enc`, Fernet) — never in code, never committed.
- NEVER bypass RiskEngine. Every entry goes through `apex/risk/risk_engine.py` first;
  the prop profile adds `PropGuard` as the account-level backstop.
- Hard stops ride INSIDE the order payload (`stop_level`), never in-memory only.
- ALL Python files: fully typed, loguru logging, docstrings on functions.
- ALL Next.js files: TypeScript strict mode, no `any` types where avoidable.
- IG DEMO account for all development. Falls back to PaperBroker with no credentials.
- `config.py` owns ALL constants. No magic numbers in logic files.
- Claude failures ALWAYS fall back to NO_TRADE — never crash the trading loop.
- Trading modules stay LOCKED until UI onboarding completes (`onboarding_complete`).

## Current Phase
v1.1 — Web-UI onboarding state + prop-firm RiskEngine (PropGuard) complete. App
launches unconfigured; IG/Claude keys + risk profile entered & validated in the UI,
saved encrypted; heartbeat gated behind completion. `prop_ftmo` profile: 0.4%/trade,
−3% daily / −8% total floating-DD breaker (liquidate + lock at 0.5% buffer).
Next (per `docs/PROP_FIRM_PLAN.md`): Phase-1 backtester (`apex/backtest/`, floating-DD
report), Lightstreamer live stream (`apex/ig/stream.py`), Phase-4 MT5/ZeroMQ bridge
(`apex/execution/`), macro calendar (news blackout).
