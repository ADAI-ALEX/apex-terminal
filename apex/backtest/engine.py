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
from apex.indicators import engine as ind
from apex.indicators.engine import build_snapshot
from apex.models import Candle, Signal
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
    open_index: int = 0

    def unrealised(self, price: float) -> float:
        sign = 1.0 if self.direction is Direction.BUY else -1.0
        return (price - self.entry) * sign * self.size


@dataclass
class BacktestResult:
    market: str
    strategy: str
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
    candles: list[dict] = field(default_factory=list)        # OHLC used (for live replay)
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
    strategy: dict | None = None,
    exo: dict[str, list[float]] | None = None,
    rr: float = 1.8,
) -> BacktestResult:
    """Replay ``candles`` through either the live strategy book (default) or a
    user-authored custom strategy.

    ``strategy`` is the resolved descriptor from :mod:`apex.strategies.store`. When
    its ``kind`` is ``custom``/``default`` the snippet is evaluated per bar via
    :class:`~apex.backtest.custom_runner.CompiledStrategy`; ``exo`` carries the
    aligned niche series (fear_greed/vix/sentiment) it can read. Anything else
    falls back to the built-in book, so existing call-sites are unaffected.
    """
    sp = params or get_settings().strategy
    strategy_name = (strategy or {}).get("name", "book")
    custom = None
    if strategy and strategy.get("kind") in ("custom", "default") and strategy.get("code"):
        from apex.backtest.custom_runner import CompiledStrategy

        custom = CompiledStrategy(str(strategy["code"]), exo=exo)

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
    # Live state exposed to custom snippets so they can manage prop-firm risk
    # (daily-loss caps, drawdown-aware sizing, daily profit lock-in).
    consec_losses = 0
    consec_wins = 0
    day_key: str | None = None
    day_open_eq = starting_equity
    trades_today = 0
    run_peak = starting_equity

    def _record_exit(ot: _OpenTrade, exit_price: float, reason: str, closed_iso: str) -> None:
        """Book a closed trade into all accumulators (shared by every exit path)."""
        nonlocal balance, wins, gross_win, gross_loss, rr_sum, consec_losses, consec_wins
        pnl = ot.unrealised(exit_price)
        balance += pnl
        ret = 100.0 * pnl / starting_equity
        trade_pnls.append(pnl)
        trade_rets.append(ret)
        if pnl >= 0:
            wins += 1
            gross_win += pnl
            consec_wins += 1
            consec_losses = 0
        else:
            gross_loss += -pnl
            consec_losses += 1
            consec_wins = 0
        risk_pts = abs(ot.entry - ot.stop)
        if risk_pts > 0:
            rr_sum += abs(exit_price - ot.entry) / risk_pts
        trade_log.append({
            "market": market.key, "direction": ot.direction.value,
            "entry": round(ot.entry, 4), "exit": round(exit_price, 4),
            "stop": round(ot.stop, 4),
            "pnl": round(pnl, 2), "ret_pct": round(ret, 3),
            "opened": ot.opened, "closed": closed_iso,
            "reason": reason, "strategy": ot.strategy,
        })

    n = len(candles)
    for i in range(min(warmup, n), n):
        bar = candles[i]
        day = bar.time.date().isoformat()
        # A custom strategy's decision depends on the bar + live state, so evaluate
        # once and reuse it for both signal-based exits and entries.
        chosen_risk: float | None = None
        if custom is not None:
            pos = (1 if open_trade and open_trade.direction is Direction.BUY
                   else -1 if open_trade and open_trade.direction is Direction.SELL else 0)
            held = (i - open_trade.open_index) if open_trade else 0
            eq_now = balance + (open_trade.unrealised(bar.close) if open_trade else 0.0)
            # Roll the trading day → reset the day-open equity + trade counter so
            # the snippet can see today's running P&L and cap its daily loss.
            if day != day_key:
                day_key = day
                day_open_eq = eq_now
                trades_today = 0
            day_pnl_pct = 100.0 * (eq_now - day_open_eq) / day_open_eq if day_open_eq else 0.0
            # Account-level (since inception) state for a hard max-loss breaker.
            run_peak = max(run_peak, eq_now)
            dd_from_peak_pct = 100.0 * (run_peak - eq_now) / run_peak if run_peak else 0.0
            total_pnl_pct = 100.0 * (eq_now - starting_equity) / starting_equity if starting_equity else 0.0
            decision, chosen_risk = custom.decide(
                i, candles, position=pos, bars_held=held, equity=eq_now,
                risk_pct=risk_pct, leverage=float(getattr(market, "fca_leverage", 0)),
                day_pnl_pct=day_pnl_pct, consec_losses=consec_losses,
                consec_wins=consec_wins, trades_today=trades_today,
                dd_from_peak_pct=dd_from_peak_pct, total_pnl_pct=total_pnl_pct,
            )
        else:
            decision = None

        # ── manage an open trade against this bar (intrabar SL/TP first) ──
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
                _record_exit(open_trade, exit_price, reason, bar.time.isoformat())
                open_trade = None

        # ── custom signal exits: FLAT closes, an opposite signal flips ────
        if open_trade is not None and decision is not None:
            flip = ((decision == "BUY" and open_trade.direction is Direction.SELL)
                    or (decision == "SELL" and open_trade.direction is Direction.BUY))
            if decision == "FLAT" or flip:
                _record_exit(open_trade, bar.close, "FLIP" if flip else "FLAT", bar.time.isoformat())
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
            if custom is not None:
                sig = _custom_entry(market, candles, i, decision, sp, atr_stop_mult, rr, strategy_name)
            else:
                window = candles[: i + 1]
                snap = build_snapshot(market.key, market.epic, window, sp)
                snap.regime = classify(market, snap, sp)
                sig = _best_signal(market, snap, window)
            if sig is not None and sig.stop_distance > 0:
                # A custom strategy may dynamically choose its per-trade risk %.
                entry_risk = chosen_risk if chosen_risk is not None else risk_pct
                risk_amt = equity * (entry_risk / 100.0)
                size = max(risk_amt / sig.stop_distance, 0.0)
                open_trade = _OpenTrade(
                    direction=sig.direction, entry=sig.entry, stop=sig.stop,
                    target=sig.target, size=size, opened=bar.time.isoformat(),
                    strategy=sig.strategy, open_index=i,
                )
                trades_today += 1

    # close any trade still open at the end
    if open_trade is not None and candles:
        _record_exit(open_trade, candles[-1].close, "END", candles[-1].time.isoformat())
        open_trade = None

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
        strategy=strategy_name,
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
        equity_curve=_downsample(equity_curve, 600),
        candles=[
            {"time": int(c.time.timestamp()), "open": round(c.open, 5), "high": round(c.high, 5),
             "low": round(c.low, 5), "close": round(c.close, 5)}
            for c in candles
        ],
        trade_log=trade_log[-200:],
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


# Price change per broker "point" for the min-stop floor. Indices and crypto
# quote 1 point = 1 price unit, but FX majors quote 1 point = 0.0001 — without
# this, a 6-point FX min-stop is read as 6.0 price units (a ~6 *dollar* stop on a
# 1.08 pair), which collapses position size to ~0. Backtest-only; the live
# RiskEngine is untouched.
_FX_POINT = 0.0001
_FX_KEYS = frozenset({"EURUSD", "GBPUSD"})


def _min_stop_price(market: Market) -> float:
    return market.min_stop_points * (_FX_POINT if market.key in _FX_KEYS else 1.0)


def _custom_entry(
    market: Market, candles: list[Candle], i: int, decision: str | None,
    sp: StrategyParams, atr_stop_mult: float, rr: float, strategy_name: str,
) -> Signal | None:
    """Turn a custom BUY/SELL decision into an ATR-sized Signal with stop + target.

    Mirrors the strategy book's sizing contract so custom strategies inherit the
    same risk model: stop = ATR × multiplier (floored at the broker minimum),
    target = stop × reward:risk.
    """
    if decision not in ("BUY", "SELL"):
        return None
    window = candles[max(0, i - 250) : i + 1]
    atr_val = ind.atr(window, sp.atr_period)
    if not atr_val or atr_val <= 0:
        return None
    entry = candles[i].close
    stop_dist = max(atr_val * atr_stop_mult, _min_stop_price(market))
    target_dist = stop_dist * rr
    direction = Direction.BUY if decision == "BUY" else Direction.SELL
    if direction is Direction.BUY:
        stop, target = entry - stop_dist, entry + target_dist
    else:
        stop, target = entry + stop_dist, entry - target_dist
    return Signal(
        market_key=market.key, epic=market.epic, strategy=strategy_name,
        direction=direction, entry=entry, stop=round(stop, 5), target=round(target, 5),
        target_rr=rr, confidence=0.6, rationale=f"custom:{strategy_name}",
    )


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
