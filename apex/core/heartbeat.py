"""Heartbeat orchestrator — three concurrent async tiers (Section 04).

* Tier 1 (30s)  : price refresh + SL/TP enforcement. Pure Python, no Claude.
* Tier 2 (5m)   : candle build → strategies → regime → RiskEngine → Claude → execute.
* Tier 3 (30m)  : Claude portfolio review → close-early / trail-stop.
* Health (5m)   : stats + watchdog heartbeat → SharedState for the dashboard.

Each loop is isolated in its own ``try/except`` so a failure in one tier never
crashes another. All blocking broker calls run in a threadpool via
``asyncio.to_thread`` so the event loop stays responsive.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from apex.agents.eod_analyst import EodAnalyst
from apex.agents.portfolio_reviewer import PortfolioReviewer
from apex.agents.signal_evaluator import SignalEvaluator
from apex.cloud import kv
from apex.config import Direction, Market, Settings, get_settings, reload_settings
from apex.core.state import STATE
from apex.ig.client import Broker, create_broker
from apex.onboarding.store import STORE
from apex.indicators.engine import build_snapshot
from apex.journal.db import TradeJournal
from apex.models import Candle, IndicatorSnapshot, Position, Signal
from apex.risk.prop_guard import PropAction, PropGuard
from apex.risk.risk_engine import RiskContext, RiskEngine
from apex.strategies import ALL_STRATEGIES
from apex.strategies.regime import classify

try:  # tz-aware close checks; degrade gracefully if tzdata missing
    from zoneinfo import ZoneInfo
    _UK = ZoneInfo("Europe/London")
except Exception:  # pragma: no cover
    _UK = timezone.utc  # type: ignore[assignment]


class Heartbeat:
    def __init__(
        self,
        broker: Broker | None = None,
        journal: TradeJournal | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.s = settings or get_settings()
        self.broker = broker or create_broker(self.s)
        self.journal = journal or TradeJournal()
        self.risk = RiskEngine(self.s.risk)
        self.prop_guard = PropGuard(self.s.prop)
        self.evaluator = SignalEvaluator()
        self.reviewer = PortfolioReviewer()
        self.eod = EodAnalyst()

        self.markets: list[Market] = self.s.active_markets()
        self.history: dict[str, list[Candle]] = {}
        self.positions: dict[str, Position] = {}      # deal_id -> Position
        self._trades_since_streak = 0
        self._weekly_halt = False
        self._eod_done_for: str | None = None
        self._running = True
        self._broker_error = ""
        self._last_backtest_id: str | None = None
        self._config_stamp = self._read_config_stamp()
        self._ig_sig = self._ig_signature()

    # ──────────────────────────────────────────────────────────────────
    #  Lifecycle
    # ──────────────────────────────────────────────────────────────────
    async def run(self) -> None:
        # Resilient connect: a bad IG login must NEVER crash the engine. On failure we
        # fall back to PaperBroker and surface the error to the dashboard so the user
        # can fix their credentials in Settings.
        await asyncio.to_thread(self._activate_broker_sync, self.broker)
        STATE.update(status=self.broker.mode, mode=self.broker.mode,
                     trading_enabled=self.s.trading_enabled, broker_error=self._broker_error)
        try:
            await self._seed_history()
            await self._sync_positions()
        except Exception as exc:  # never crash startup on a data hiccup
            logger.exception("Startup data load failed (continuing): {}", exc)
        logger.info("Heartbeat starting — {} markets, mode={}", len(self.markets), self.broker.mode)

        await asyncio.gather(
            self._loop(self._tier1, self.s.heartbeat.tier1_price_seconds, "Tier1"),
            self._loop(self._tier2, self.s.heartbeat.tier2_signal_seconds, "Tier2"),
            self._loop(self._tier3, self.s.heartbeat.tier3_portfolio_seconds, "Tier3"),
            self._loop(self._health, self.s.heartbeat.health_seconds, "Health"),
            self._loop(self._config_watch, 8, "ConfigWatch"),
            self._loop(self._backtest_watch, 5, "Backtest"),
        )

    def stop(self) -> None:
        self._running = False

    async def _loop(self, fn, interval: int, name: str) -> None:
        """Run ``fn`` every ``interval`` seconds, swallowing per-cycle errors."""
        while self._running:
            try:
                await fn()
            except Exception as exc:  # isolation: never let one tier kill the loop
                logger.exception("{} cycle error: {}", name, exc)
            await asyncio.sleep(interval)

    # ──────────────────────────────────────────────────────────────────
    #  Tier 1 — price + SL/TP enforcement
    # ──────────────────────────────────────────────────────────────────
    async def _tier1(self) -> None:
        await self._sync_positions()
        for pos in list(self.positions.values()):
            pos.current_price = await asyncio.to_thread(self.broker.latest_price, pos.epic)
            reason = self.risk.stop_or_target_hit(pos)
            if reason:
                await self._close(pos, reason)
        await self._prop_check()
        self._push_state()
        await self._publish_kv()

    async def _prop_check(self) -> None:
        """Prop-firm floating-equity circuit breaker (sampled every Tier-1 cycle).

        On LIQUIDATE: flatten every open position immediately and latch the lock so
        Tier 2 takes no new entries until the daily reset (or a manual restart on a
        total-drawdown breach). Hard stops already ride in each order payload, so
        this is the *account-level* backstop on top of per-position stops.
        """
        equity = await asyncio.to_thread(self._floating_equity)
        decision = self.prop_guard.evaluate(equity)
        STATE.prop = {
            "enabled": self.s.prop.enabled,
            "action": decision.action.value,
            "daily_dd_pct": round(decision.daily_dd_pct, 2),
            "total_dd_pct": round(decision.total_dd_pct, 2),
            "daily_limit_pct": self.s.prop.daily_dd_limit_pct,
            "total_limit_pct": self.s.prop.total_dd_limit_pct,
            "locked": decision.locked,
            "reason": decision.reason,
        }
        if decision.action is PropAction.LIQUIDATE and self.positions:
            logger.error("PropGuard LIQUIDATE — flattening {} position(s): {}",
                         len(self.positions), decision.reason)
            for pos in list(self.positions.values()):
                await self._close(pos, "PROP_BREAKER")

    def _floating_equity(self) -> float:
        """Account balance + open (floating) P&L — what a prop auditor measures."""
        account = self.broker.account()
        base = account.balance or self.s.starting_equity
        unrealised = sum(p.unrealised_pnl for p in self.positions.values())
        return float(base) + float(unrealised)

    # ──────────────────────────────────────────────────────────────────
    #  Tier 2 — signal generation + Claude + execution
    # ──────────────────────────────────────────────────────────────────
    async def _tier2(self) -> None:
        for market in self.markets:
            candles = await self._refresh_market(market)
            if len(candles) < 60:
                continue
            snapshot = build_snapshot(market.key, market.epic, candles, self.s.strategy)
            snapshot.regime = classify(market, snapshot, self.s.strategy)
            STATE.snapshots[market.key] = snapshot
            STATE.candles[market.key] = self._candle_view(candles)

            signal = self._best_signal(market, snapshot, candles)
            if signal is None:
                continue
            await self._maybe_enter(signal, snapshot)
        self._push_state()

    @staticmethod
    def _candle_view(candles: list[Candle], limit: int = 150) -> list[dict]:
        """Compact OHLC slice for the dashboard chart (epoch seconds + OHLC)."""
        return [
            {
                "time": int(c.time.timestamp()),
                "open": round(c.open, 5), "high": round(c.high, 5),
                "low": round(c.low, 5), "close": round(c.close, 5),
            }
            for c in candles[-limit:]
        ]

    def _best_signal(
        self, market: Market, snapshot: IndicatorSnapshot, candles: list[Candle]
    ) -> Signal | None:
        candidates: list[Signal] = []
        for strat in ALL_STRATEGIES:
            if not strat.has_authority(snapshot.regime):
                continue
            sig = strat.evaluate(market, snapshot, candles)
            if sig is not None:
                candidates.append(sig)
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.confidence)

    async def _maybe_enter(self, signal: Signal, snapshot: IndicatorSnapshot) -> None:
        if self.prop_guard.locked:
            logger.debug("Prop circuit breaker locked — skipping {} {}.",
                         signal.direction.value, signal.market_key)
            return
        ctx = self._risk_context(signal)
        decision = self.risk.evaluate_entry(signal, ctx)
        if not decision.allowed:
            logger.debug("Risk blocked {} {}: {}", signal.direction.value,
                         signal.market_key, "; ".join(decision.reasons))
            return

        verdict = await asyncio.to_thread(
            self.evaluator.evaluate, signal, snapshot, list(self.positions.values()),
        )
        STATE.bump_api("claude")
        if not verdict.approved:
            return

        # Apply Claude's (risk-only) tightening, if any.
        if verdict.adjusted_stop is not None:
            signal.stop = verdict.adjusted_stop
        if verdict.adjusted_target is not None:
            signal.target = verdict.adjusted_target
        signal.confidence = max(signal.confidence, verdict.confidence)

        pos = await asyncio.to_thread(self.broker.open_position, signal, decision.size)
        STATE.bump_api("ig")
        if pos is not None:
            self.positions[pos.deal_id] = pos
            self._trades_since_streak += 1

    # ──────────────────────────────────────────────────────────────────
    #  Tier 3 — portfolio review
    # ──────────────────────────────────────────────────────────────────
    async def _tier3(self) -> None:
        await self._sync_positions()
        positions = list(self.positions.values())
        review = await asyncio.to_thread(self.reviewer.review, positions)
        STATE.bump_api("claude")
        STATE.update(portfolio_health=review.health_score)

        by_id = {p.deal_id: p for p in positions}
        for rec in review.recommendations:
            pos = by_id.get(rec.deal_id)
            if pos is None:
                continue
            if rec.action.upper() == "CLOSE":
                await self._close(pos, "AI_REVIEW")
            elif rec.action.upper() == "TRAIL_STOP" and rec.new_stop is not None:
                pos.stop_price = rec.new_stop  # tightening only; broker amend left to live impl
                logger.info("Trailed stop on {} to {}", pos.market_key, rec.new_stop)

        # Overnight low-conviction flattening.
        now = datetime.now(timezone.utc)
        for pos in list(self.positions.values()):
            if self.risk.should_close_overnight(pos, now):
                await self._close(pos, "EOD")
        await self._maybe_run_eod(now)
        self._push_state()

    async def _maybe_run_eod(self, now: datetime) -> None:
        today = now.date().isoformat()
        if now.hour >= 18 and self._eod_done_for != today:
            report = await asyncio.to_thread(self.eod.analyse, self.journal.recent(50), self.journal.stats())
            STATE.bump_api("claude")
            self._eod_done_for = today
            logger.info("EOD complete (score {}).", report.day_score)

    # ──────────────────────────────────────────────────────────────────
    #  Health — stats + watchdog
    # ──────────────────────────────────────────────────────────────────
    async def _health(self) -> None:
        self._push_state()
        await self._publish_kv()
        logger.info("♥ alive | positions={} daily=£{:.2f} ({:.1f}%) mode={}",
                    len(self.positions), STATE.daily_pnl, STATE.daily_pnl_pct, self.broker.mode)

    # ──────────────────────────────────────────────────────────────────
    #  Config watcher — apply Settings changes saved from the dashboard
    # ──────────────────────────────────────────────────────────────────
    async def _config_watch(self) -> None:
        """Detect a config change (e.g. Settings page → KV) and apply it live."""
        stamp = self._read_config_stamp()
        if stamp is None or stamp == self._config_stamp:
            return
        logger.info("Config change detected — applying new settings.")
        self._config_stamp = stamp
        await asyncio.to_thread(self._apply_settings_change)

    def _apply_settings_change(self) -> None:
        """Reload settings and swap the affected components (defensive; never raises)."""
        try:
            reload_settings()
            new = get_settings()
            prop_changed = new.prop != self.s.prop
            ig_changed = self._ig_signature() != self._ig_sig
            self.s = new
            self.risk = RiskEngine(self.s.risk)
            self.markets = self.s.active_markets()
            # Re-create agents so a new Claude key / model takes effect.
            self.evaluator = SignalEvaluator()
            self.reviewer = PortfolioReviewer()
            self.eod = EodAnalyst()
            if prop_changed:
                self.prop_guard = PropGuard(self.s.prop)  # new limits → fresh baseline
            if ig_changed:
                self._activate_broker_sync(create_broker(self.s))  # resilient re-connect
                self._ig_sig = self._ig_signature()
            STATE.update(trading_enabled=self.s.trading_enabled, status=self.broker.mode,
                         broker_error=self._broker_error)
            self._push_state()  # refresh ai_enabled/breakers immediately
            if kv.kv_enabled():  # publish now so the dashboard reflects it on its next poll
                try:
                    kv.kv_set(kv.STATE_KEY, STATE.snapshot())
                except Exception:
                    pass
            logger.info("Settings applied (profile={}, ai={}, markets={}).",
                        self.s.risk_profile, "on" if self.s.ai_enabled else "off",
                        ",".join(m.key for m in self.markets))
        except Exception as exc:
            logger.exception("Failed to apply settings change: {}", exc)

    # ──────────────────────────────────────────────────────────────────
    #  Backtest watcher — run requests posted from the dashboard (cloud relay)
    # ──────────────────────────────────────────────────────────────────
    async def _backtest_watch(self) -> None:
        if not kv.kv_enabled():
            return
        req = await asyncio.to_thread(kv.kv_get, kv.BACKTEST_REQ_KEY)
        if not req or not isinstance(req, dict):
            return
        rid = str(req.get("id", ""))
        if not rid or rid == self._last_backtest_id:
            return
        self._last_backtest_id = rid
        logger.info("Backtest request {} — running on real data...", rid)
        result = await asyncio.to_thread(self.run_backtest_request, req)
        await asyncio.to_thread(kv.kv_set, kv.BACKTEST_RES_KEY, {"id": rid, **result})
        logger.info("Backtest {} complete.", rid)

    def run_backtest_request(self, req: dict) -> dict:
        """Fetch historical candles via the broker and run the backtest engine."""
        from apex.backtest.runner import run_request

        return run_request(self.broker, self.s, req)

    def _read_config_stamp(self) -> str | None:
        try:
            data = STORE.load() or {}
            return data.get("configured_at")
        except Exception:
            return None

    def _ig_signature(self) -> tuple:
        return (self.s.ig_username, self.s.ig_password, self.s.ig_api_key, self.s.ig_acc_type.value)

    def _activate_broker_sync(self, broker: Broker) -> None:
        """Connect ``broker``; on failure record a friendly error and fall back to
        PaperBroker so the engine stays alive and the dashboard keeps updating."""
        from apex.ig.client import PaperBroker
        try:
            broker.connect()
            self.broker = broker
            self._broker_error = ""
        except Exception as exc:
            msg = _friendly_ig_error(exc)
            logger.error("Broker connect failed — running in PAPER (simulation): {}", msg)
            self._broker_error = msg
            self.broker = PaperBroker(self.s)
            try:
                self.broker.connect()
            except Exception:  # paper connect can't really fail, but be safe
                pass

    async def _publish_kv(self) -> None:
        """Push the live snapshot to Vercel KV so the dashboard can read it from
        anywhere (cloud-relay mode). No-op when KV isn't configured."""
        if not kv.kv_enabled():
            return
        try:
            await asyncio.to_thread(kv.kv_set, kv.STATE_KEY, STATE.snapshot())
        except Exception as exc:  # never let telemetry break the loop
            logger.debug("KV state publish skipped: {}", exc)

    # ──────────────────────────────────────────────────────────────────
    #  Shared helpers
    # ──────────────────────────────────────────────────────────────────
    async def _seed_history(self) -> None:
        n = self.s.heartbeat.history_candles
        m = self.s.heartbeat.candle_minutes_default
        for market in self.markets:
            candles = await asyncio.to_thread(self.broker.candles, market.epic, m, n)
            self.history[market.key] = candles
            STATE.candles[market.key] = self._candle_view(candles)   # chart has data on first load

    async def _refresh_market(self, market: Market) -> list[Candle]:
        n = self.s.heartbeat.history_candles
        m = self.s.heartbeat.candle_minutes_default
        candles = await asyncio.to_thread(self.broker.candles, market.epic, m, n)
        STATE.bump_api("ig")
        self.history[market.key] = candles
        return candles

    async def _sync_positions(self) -> None:
        broker_positions = await asyncio.to_thread(self.broker.positions)
        # Preserve our strategy/confidence metadata where deal ids match.
        merged: dict[str, Position] = {}
        for bp in broker_positions:
            existing = self.positions.get(bp.deal_id)
            if existing:
                bp.strategy = existing.strategy
                bp.confidence = existing.confidence
                bp.opened_at = existing.opened_at
            merged[bp.deal_id] = bp
        self.positions = merged

    async def _close(self, position: Position, reason: str) -> None:
        record = await asyncio.to_thread(self.broker.close_position, position, reason)
        STATE.bump_api("ig")
        self.positions.pop(position.deal_id, None)
        if record is not None:
            self.journal.record(record)
            if record.pnl >= 0:
                self._trades_since_streak = 0  # streak broken
            logger.info("Closed {} ({}) → £{:.2f}", position.market_key, reason, record.pnl)

    def _risk_context(self, signal: Signal) -> RiskContext:
        account = self._refresh_account()
        positions = list(self.positions.values())
        consec = self.journal.consecutive_losses()
        market = next((m for m in self.markets if m.key == signal.market_key), None)
        return RiskContext(
            account=account,
            open_positions=positions,
            daily_pnl_pct=STATE.daily_pnl_pct,
            weekly_pnl_pct=STATE.weekly_pnl_pct,
            consecutive_losses=consec,
            trades_since_streak=self._trades_since_streak,
            news_blackout=self._news_blackout(),
            within_close_buffer=self._within_close_buffer(market) if market else False,
            weekly_halt=self._weekly_halt,
        )

    def _refresh_account(self):  # type: ignore[no-untyped-def]
        account = self.broker.account()
        realised_daily = self.journal.daily_pnl()
        realised_weekly = self.journal.weekly_pnl()
        unrealised = sum(p.unrealised_pnl for p in self.positions.values())
        equity = max(account.equity or account.balance, 1.0)
        daily = realised_daily + unrealised
        weekly = realised_weekly + unrealised
        if weekly / equity * 100.0 <= self.s.risk.weekly_loss_limit_pct:
            self._weekly_halt = True
        STATE.update(
            account=account, daily_pnl=daily, weekly_pnl=weekly,
            daily_pnl_pct=100.0 * daily / equity, weekly_pnl_pct=100.0 * weekly / equity,
            stats=self.journal.stats(),
        )
        return account

    def _news_blackout(self) -> bool:
        """Hook for a macro calendar. No calendar wired yet → never blackout."""
        return False

    def _within_close_buffer(self, market: Market) -> bool:
        try:
            now_uk = datetime.now(_UK)
            hh, mm = market.close_utc.split(":")
            close = now_uk.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            buffer = timedelta(minutes=self.s.risk.market_close_buffer_minutes)
            return close - buffer <= now_uk <= close
        except Exception:
            return False

    def _push_state(self) -> None:
        STATE.update(
            positions=list(self.positions.values()),
            trading_enabled=self.s.trading_enabled,
            status="HALTED" if self._weekly_halt else self.broker.mode,
            breakers=self._breaker_state(),
            broker_error=self._broker_error,
            ai_enabled=self.s.ai_enabled,
        )

    def _breaker_state(self) -> dict[str, bool]:
        r = self.s.risk
        breakers = {
            "daily_loss": STATE.daily_pnl_pct <= r.daily_loss_limit_pct,
            "weekly_loss": self._weekly_halt,
            "max_positions": len(self.positions) >= r.max_concurrent_positions,
            "consecutive_losses": self.journal.consecutive_losses() >= r.consecutive_loss_trigger,
            "trading_disabled": not self.s.trading_enabled,
        }
        if self.s.prop.enabled:
            breakers["prop_circuit"] = self.prop_guard.locked
        return breakers


def _friendly_ig_error(exc: Exception) -> str:
    """Map IG's cryptic error codes to actionable messages for the dashboard."""
    raw = str(exc) or exc.__class__.__name__
    hints = {
        "validation.pattern.invalid.authenticationRequest.identifier":
            "IG rejected the username format — use your IG username (not your email).",
        "error.security.invalid-details":
            "IG rejected the username or password.",
        "error.security.invalid-application-key":
            "IG API key is invalid for this account/environment.",
        "error.security.api-key-invalid":
            "IG API key is invalid.",
        "error.security.api-key-disabled":
            "This IG API key is disabled — generate a new one in My IG.",
        "error.public-api.failure.encryption.required":
            "IG requires the encrypted-login flow for this key.",
    }
    for code, msg in hints.items():
        if code in raw:
            return f"{msg} (IG: {raw})"
    return f"IG connection failed: {raw}"
