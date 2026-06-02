"""Backtesting — replay strategies over historical candles with prop-firm metrics.

`engine.run_backtest` is pure (candles in, metrics out) so it's testable and reusable
by both the local state server and the cloud-relay runner on the laptop.
"""

from apex.backtest.engine import BacktestResult, run_backtest

__all__ = ["BacktestResult", "run_backtest"]
