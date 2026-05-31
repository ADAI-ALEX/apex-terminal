"""RiskEngine — the single mandatory gate between a signal and the broker.

Every entry must pass :meth:`RiskEngine.evaluate_entry`, which:

1. Runs the 9 circuit breakers (Section 06). Any hard breaker → blocked.
2. Sizes the position from ATR (Section 03), auto-reducing — never increasing —
   to respect per-trade, total-open, leverage and single-trade caps.

The engine is deliberately *pure*: it takes a :class:`RiskContext` snapshot and
returns a :class:`~apex.models.RiskDecision`. It holds no broker handle and places
no orders, which is what makes it exhaustively unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone

from loguru import logger

from apex.config import Direction, RiskParams, get_settings
from apex.models import AccountSnapshot, Position, RiskDecision, Signal


@dataclass
class RiskContext:
    """Everything the risk engine needs to decide, captured at one instant."""

    account: AccountSnapshot
    open_positions: list[Position] = field(default_factory=list)
    daily_pnl_pct: float = 0.0          # realised+unrealised today, % of account
    weekly_pnl_pct: float = 0.0
    consecutive_losses: int = 0
    trades_since_streak: int = 0        # trades taken since the loss streak triggered
    news_blackout: bool = False         # within blackout window of a major event
    within_close_buffer: bool = False   # signal's instrument is near session close
    weekly_halt: bool = False           # latched halt requiring manual restart


class RiskEngine:
    def __init__(self, params: RiskParams | None = None) -> None:
        self.p = params or get_settings().risk

    # ──────────────────────────────────────────────────────────────────
    #  Entry gate
    # ──────────────────────────────────────────────────────────────────
    def evaluate_entry(self, signal: Signal, ctx: RiskContext) -> RiskDecision:
        reasons: list[str] = []

        # ── Hard breakers (block outright) ────────────────────────────
        if not get_settings().trading_enabled:
            return RiskDecision(allowed=False, reasons=["TRADING_ENABLED=false (kill switch)"])
        if ctx.weekly_halt or ctx.weekly_pnl_pct <= self.p.weekly_loss_limit_pct:
            return RiskDecision(allowed=False, reasons=[
                f"Weekly loss limit hit ({ctx.weekly_pnl_pct:.1f}% <= {self.p.weekly_loss_limit_pct}%) — manual restart required"])
        if ctx.daily_pnl_pct <= self.p.daily_loss_limit_pct:
            return RiskDecision(allowed=False, reasons=[
                f"Daily loss limit hit ({ctx.daily_pnl_pct:.1f}% <= {self.p.daily_loss_limit_pct}%)"])
        if len(ctx.open_positions) >= self.p.max_concurrent_positions:
            return RiskDecision(allowed=False, reasons=[
                f"Max concurrent positions ({len(ctx.open_positions)}/{self.p.max_concurrent_positions})"])
        if ctx.news_blackout:
            return RiskDecision(allowed=False, reasons=["News blackout window — no new entries"])
        if ctx.within_close_buffer:
            return RiskDecision(allowed=False, reasons=["Within market-close buffer — no new entries"])
        if self._duplicate_position(signal, ctx):
            return RiskDecision(allowed=False, reasons=[f"Already in {signal.market_key}"])

        # ── Sizing ────────────────────────────────────────────────────
        size, sizing_notes = self._size_position(signal, ctx)
        reasons.extend(sizing_notes)

        if size < self.p.min_stake_per_point:
            return RiskDecision(allowed=False, size=0.0, reasons=[
                *reasons, f"Sized below IG minimum (£{size:.2f} < £{self.p.min_stake_per_point}/pt)"])

        # ── Total open risk cap ───────────────────────────────────────
        new_risk = size * signal.stop_distance
        open_risk = self._open_risk(ctx)
        equity = max(ctx.account.equity or ctx.account.balance, 1.0)
        total_risk_pct = 100.0 * (open_risk + new_risk) / equity
        if total_risk_pct > self.p.max_total_open_risk_pct:
            return RiskDecision(allowed=False, size=0.0, reasons=[
                *reasons,
                f"Total open risk would be {total_risk_pct:.1f}% > {self.p.max_total_open_risk_pct}%"])

        return RiskDecision(allowed=True, size=round(size, 2), risk_amount=round(new_risk, 2), reasons=reasons)

    # ──────────────────────────────────────────────────────────────────
    #  Position sizing (ATR-based, with auto-reductions only)
    # ──────────────────────────────────────────────────────────────────
    def _size_position(self, signal: Signal, ctx: RiskContext) -> tuple[float, list[str]]:
        notes: list[str] = []
        equity = max(ctx.account.equity or ctx.account.balance, 1.0)
        stop_points = signal.stop_distance
        if stop_points <= 0:
            return 0.0, ["Invalid stop distance"]

        # Base risk = max_risk_per_trade_pct of equity.
        risk_amount = equity * (self.p.max_risk_per_trade_pct / 100.0)
        size = risk_amount / stop_points

        # Consecutive-loss throttle.
        if ctx.consecutive_losses >= self.p.consecutive_loss_trigger and \
                ctx.trades_since_streak < self.p.consecutive_loss_cooldown_trades:
            size *= self.p.consecutive_loss_size_factor
            notes.append(
                f"Consecutive-loss throttle ×{self.p.consecutive_loss_size_factor} "
                f"({ctx.consecutive_losses} losses)")

        # Single-trade hard ceiling (% of equity).
        cap_amount = equity * (self.p.single_trade_risk_cap_pct / 100.0)
        if size * stop_points > cap_amount:
            size = cap_amount / stop_points
            notes.append(f"Capped to single-trade ceiling ({self.p.single_trade_risk_cap_pct}%)")

        # Effective-leverage cap: notional = size * entry * point_value (1.0).
        notional = size * signal.entry
        max_notional = equity * self.p.max_effective_leverage
        if notional > max_notional and signal.entry > 0:
            size = max_notional / signal.entry
            notes.append(f"Capped to {self.p.max_effective_leverage}:1 effective leverage")

        return max(size, 0.0), notes

    # ──────────────────────────────────────────────────────────────────
    #  Exit-side helpers (used by Tier-1 / Tier-3)
    # ──────────────────────────────────────────────────────────────────
    def should_close_overnight(self, position: Position, now: datetime | None = None) -> bool:
        """Close low-conviction positions after the overnight cutoff."""
        now = now or datetime.now(timezone.utc)
        cutoff = _parse_hhmm(self.p.overnight_cutoff_uk)
        if now.timetz().replace(tzinfo=None) < cutoff:
            return False
        # Keep only positions already showing healthy profit toward target.
        return position.unrealised_points < self.p.overnight_min_profit_points

    def stop_or_target_hit(self, position: Position) -> str | None:
        if position.stop_hit():
            return "SL"
        if position.target_hit():
            return "TP"
        return None

    # ──────────────────────────────────────────────────────────────────
    #  internals
    # ──────────────────────────────────────────────────────────────────
    def _open_risk(self, ctx: RiskContext) -> float:
        """£ currently at risk across open positions (distance to stop × size)."""
        total = 0.0
        for pos in ctx.open_positions:
            total += abs(pos.entry_price - pos.stop_price) * pos.size
        return total

    @staticmethod
    def _duplicate_position(signal: Signal, ctx: RiskContext) -> bool:
        return any(p.market_key == signal.market_key for p in ctx.open_positions)


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))
