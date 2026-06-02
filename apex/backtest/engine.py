"""Backtest engine — replays the live strategy book over historical candles.

It reuses the exact production logic (``build_snapshot`` → ``classify`` regime →
``ALL_STRATEGIES`` → ATR-sized entry with stop/target), so a backtest reflects what
the engine would actually do. Exits are evaluated **intrabar** (against each bar's
high/low) and **floating equity** is marked every bar — the way a prop auditor measures
drawdown. A Monte-Carlo bootstrap then estimates the probability of passing the
challenge without a breach.

Pure function: candles in, metrics out. No broker, no network.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field

from apex.config import Direction, Market, StrategyParams, get_settings
from apex.indicators.engine import build_snapshot
from apex.models import Candle
from apex.strategies import ALL_STRATEGIES
from apex.strategies.regime import classify


@dataclass
class _OpenTrade:
    direction: Direction
    entry: float
    stop: float
    target: float
    size: float
    opened: str
    strategy: str

    def unrealised(self, price: float) -> float:
        sign = 1.0 if self.direction is Direction.BUY else -1.0
        return (price - self.entry) * sign * self.size


@dataclass
class BacktestResult:
    market: str
    bars: int
    starting_equity: float
    final_equity: float
    total_return_pct: float
    trades: int
    win_rate: float
    profit_factor: float
    avg_rr: float
    expectancy_pct: float
    max_daily_dd_pct: float
    max_total_dd_pct: float
    equity_curve: list[dict] = field(default_factory=list)   # [{time, equity}]
    trade_log: list[dict] = field(default_factory=list)
    monte_carlo: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def run_backtest(
    candles: list[Candle],
    market: Market,
    *,
    starting_equity: float = 100_000.0,
    risk_pct: float = 0.4,
    atr_stop_mult: float = 1.5,
    warmup: int = 60,
    params: StrategyParams | None = None,
    mc_runs: int = 500,
    target_pct: float = 10.0,
    total_limit_pct: float = 10.0,
    seed: int = 7,
) -> BacktestResult:
    sp = params or get_settings().strategy
    balance = starting_equity
    peak = starting_equity
    max_total_dd = 0.0
    open_trade: _OpenTrade | None = None
    trade_pnls: list[float] = []
    trade_rets: list[float] = []
    wins = gross_win = gross_loss = 0.0
    rr_sum = 0.0
    trade_log: list[dict] = []
    equity_curve: list[dict] = []
    day_start_eq: dict[str, float] = {}
    day_min_eq: dict[str, float] = {}

    n = len(candles)
    for i in range(min(warmup, n), n):
        bar = candles[i]
        day = bar.time.date().isoformat()

        # ── manage an open trade against this bar (intrabar) ──────────
        if open_trade is not None:
            exit_price = reason = None
            if open_trade.direction is Direction.BUY:
                if bar.low <= open_trade.stop:
                    exit_price, reason = open_trade.stop, "SL"
                elif bar.high >= open_trade.target:
                    exit_price, reason = open_trade.target, "TP"
            else:
                if bar.high >= open_trade.stop:
                    exit_price, reason = open_trade.stop, "SL"
                elif bar.low <= open_trade.target:
                    exit_price, reason = open_trade.target, "TP"
            if exit_price is not None:
                pnl = open_trade.unrealised(exit_price)
                balance += pnl
                ret = 100.0 * pnl / starting_equity
                trade_pnls.append(pnl)
                trade_rets.append(ret)
                if pnl >= 0:
                    wins += 1
                    gross_win += pnl
                else:
                    gross_loss += -pnl
                risk_pts = abs(open_trade.entry - open_trade.stop)
                if risk_pts > 0:
                    rr_sum += abs(exit_price - open_trade.entry) / risk_pts
                trade_log.append({
                    "market": market.key, "direction": open_trade.direction.value,
                    "entry": round(open_trade.entry, 4), "exit": round(exit_price, 4),
                    "pnl": round(pnl, 2), "ret_pct": round(ret, 3),
                    "opened": open_trade.opened, "closed": bar.time.isoformat(),
                    "reason": reason, "strategy": open_trade.strategy,
                })
                open_trade = None

        # ── mark floating equity + drawdowns ──────────────────────────
        floating = open_trade.unrealised(bar.close) if open_trade else 0.0
        equity = balance + floating
        peak = max(peak, equity)
        max_total_dd = max(max_total_dd, 100.0 * (peak - equity) / peak if peak > 0 else 0.0)
        day_start_eq.setdefault(day, equity)
        day_min_eq[day] = min(day_min_eq.get(day, equity), equity)
        equity_curve.append({"time": int(bar.time.timestamp()), "equity": round(equity, 2)})

        # ── look for a new entry when flat ────────────────────────────
        if open_trade is None:
            window = candles[: i + 1]
            snap = build_snapshot(market.key, market.epic, window, sp)
            snap.regime = classify(market, snap, sp)
            sig = _best_signal(market, snap, window)
            if sig is not None and sig.stop_distance > 0:
                risk_amt = equity * (risk_pct / 100.0)
                size = max(risk_amt / sig.stop_distance, 0.0)
                open_trade = _OpenTrade(
                    direction=sig.direction, entry=sig.entry, stop=sig.stop,
                    target=sig.target, size=size, opened=bar.time.isoformat(),
                    strategy=sig.strategy,
                )

    # close any trade still open at the end
    if open_trade is not None and candles:
        last = candles[-1].close
        pnl = open_trade.unrealised(last)
        balance += pnl
        trade_pnls.append(pnl)
        trade_rets.append(100.0 * pnl / starting_equity)
        if pnl >= 0:
            wins += 1
            gross_win += pnl
        else:
            gross_loss += -pnl
        trade_log.append({
            "market": market.key, "direction": open_trade.direction.value,
            "entry": round(open_trade.entry, 4), "exit": round(last, 4),
            "pnl": round(pnl, 2), "ret_pct": round(100.0 * pnl / starting_equity, 3),
            "opened": open_trade.opened, "closed": candles[-1].time.isoformat(),
            "reason": "END", "strategy": open_trade.strategy,
        })

    trades = len(trade_pnls)
    max_daily_dd = 0.0
    for day, start_eq in day_start_eq.items():
        if start_eq > 0:
            max_daily_dd = max(max_daily_dd, 100.0 * (start_eq - day_min_eq[day]) / start_eq)

    win_rate = round(100.0 * wins / trades, 1) if trades else 0.0
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    avg_rr = round(rr_sum / trades, 2) if trades else 0.0
    expectancy_pct = round(sum(trade_rets) / trades, 3) if trades else 0.0
    final_equity = round(balance, 2)

    return BacktestResult(
        market=market.key,
        bars=n,
        starting_equity=starting_equity,
        final_equity=final_equity,
        total_return_pct=round(100.0 * (balance - starting_equity) / starting_equity, 2),
        trades=trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_rr=avg_rr,
        expectancy_pct=expectancy_pct,
        max_daily_dd_pct=round(max_daily_dd, 2),
        max_total_dd_pct=round(max_total_dd, 2),
        equity_curve=_downsample(equity_curve, 400),
        trade_log=trade_log[-100:],
        monte_carlo=_monte_carlo(trade_rets, starting_equity, mc_runs, target_pct, total_limit_pct, seed),
    )


def _best_signal(market: Market, snap, window):  # type: ignore[no-untyped-def]
    candidates = []
    for strat in ALL_STRATEGIES:
        if not strat.has_authority(snap.regime):
            continue
        sig = strat.evaluate(market, snap, window)
        if sig is not None:
            candidates.append(sig)
    return max(candidates, key=lambda s: s.confidence) if candidates else None


def _monte_carlo(
    trade_rets: list[float], starting_equity: float, runs: int,
    target_pct: float, total_limit_pct: float, seed: int,
) -> dict:
    """Bootstrap-resample the trade returns to estimate pass / breach probabilities."""
    if len(trade_rets) < 5:
        return {"runs": 0, "note": "Not enough trades for a meaningful Monte Carlo."}
    rng = random.Random(seed)
    n = len(trade_rets)
    finals: list[float] = []
    pass_count = breach_count = 0
    for _ in range(runs):
        equity_pct = 0.0
        peak = 0.0
        passed = breached = False
        for _ in range(n):
            equity_pct += rng.choice(trade_rets)
            peak = max(peak, equity_pct)
            if peak - equity_pct >= total_limit_pct:
                breached = True
                break
            if equity_pct >= target_pct:
                passed = True
                break
        finals.append(equity_pct)
        pass_count += passed
        breach_count += breached
    finals.sort()
    return {
        "runs": runs,
        "pass_prob_pct": round(100.0 * pass_count / runs, 1),
        "breach_prob_pct": round(100.0 * breach_count / runs, 1),
        "median_return_pct": round(finals[len(finals) // 2], 2),
        "p5_return_pct": round(finals[max(0, int(0.05 * len(finals)))], 2),
        "p95_return_pct": round(finals[min(len(finals) - 1, int(0.95 * len(finals)))], 2),
        "target_pct": target_pct,
        "total_limit_pct": total_limit_pct,
    }


def _downsample(points: list[dict], limit: int) -> list[dict]:
    if len(points) <= limit:
        return points
    step = len(points) / limit
    return [points[int(i * step)] for i in range(limit)]
