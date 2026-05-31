"""Strategy package — signal generators gated by the regime detector."""

from apex.strategies.atr_breakout import AtrBreakoutStrategy
from apex.strategies.base import Strategy
from apex.strategies.ema_trend import EmaTrendStrategy
from apex.strategies.rsi_reversion import RsiReversionStrategy

# Order matters only for deterministic iteration in tests/logging.
ALL_STRATEGIES: list[Strategy] = [
    EmaTrendStrategy(),
    RsiReversionStrategy(),
    AtrBreakoutStrategy(),
]

__all__ = [
    "Strategy",
    "EmaTrendStrategy",
    "RsiReversionStrategy",
    "AtrBreakoutStrategy",
    "ALL_STRATEGIES",
]
