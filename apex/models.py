"""Typed domain models shared across the system.

Pydantic gives us validation at the boundaries (IG payloads, Claude JSON) and
clean serialization for the state server the dashboard consumes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from apex.config import Direction, Regime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Candle(BaseModel):
    """A single OHLC candle. Time is the bar's open time (UTC)."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class IndicatorSnapshot(BaseModel):
    """All computed indicators for one instrument at one moment."""

    epic: str
    market_key: str
    price: float
    ema_fast: float | None = None
    ema_mid: float | None = None
    ema_slow: float | None = None
    rsi: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    atr: float | None = None
    atr_prev: float | None = None
    bb_upper: float | None = None
    bb_mid: float | None = None
    bb_lower: float | None = None
    adx: float | None = None
    regime: Regime | None = None
    computed_at: datetime = Field(default_factory=_utcnow)


class Signal(BaseModel):
    """A trade idea produced by a strategy, before risk/Claude approval."""

    market_key: str
    epic: str
    strategy: str
    direction: Direction
    entry: float
    stop: float
    target: float
    target_rr: float
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    rationale: str = ""
    regime: Regime | None = None
    created_at: datetime = Field(default_factory=_utcnow)

    @property
    def stop_distance(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def target_distance(self) -> float:
        return abs(self.target - self.entry)


class AgentDecision(BaseModel):
    """Structured output from the Claude Signal Evaluator."""

    action: str = "NO_TRADE"           # ENTER | NO_TRADE
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    reasoning: str = ""
    adjusted_stop: float | None = None
    adjusted_target: float | None = None

    @property
    def approved(self) -> bool:
        return self.action.upper() == "ENTER"


class Position(BaseModel):
    """An open position as tracked locally (mirrors IG, enriched with our metadata)."""

    deal_id: str
    market_key: str
    epic: str
    direction: Direction
    size: float                      # £/pt stake
    entry_price: float
    stop_price: float
    target_price: float
    current_price: float
    strategy: str = ""
    confidence: float = 0.0
    opened_at: datetime = Field(default_factory=_utcnow)

    @property
    def unrealised_points(self) -> float:
        sign = 1.0 if self.direction is Direction.BUY else -1.0
        return (self.current_price - self.entry_price) * sign

    @property
    def unrealised_pnl(self) -> float:
        return self.unrealised_points * self.size

    @property
    def stop_distance_remaining(self) -> float:
        return abs(self.current_price - self.stop_price)

    @property
    def target_distance_remaining(self) -> float:
        return abs(self.target_price - self.current_price)

    def stop_hit(self) -> bool:
        if self.direction is Direction.BUY:
            return self.current_price <= self.stop_price
        return self.current_price >= self.stop_price

    def target_hit(self) -> bool:
        if self.direction is Direction.BUY:
            return self.current_price >= self.target_price
        return self.current_price <= self.target_price


class TradeRecord(BaseModel):
    """A closed trade written to the journal."""

    deal_id: str
    market_key: str
    direction: Direction
    strategy: str
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    points: float
    exit_reason: str                 # SL | TP | MANUAL | EOD | RISK | CLOSE_BUFFER
    confidence: float = 0.0
    reasoning: str = ""
    opened_at: datetime
    closed_at: datetime = Field(default_factory=_utcnow)


class AccountSnapshot(BaseModel):
    balance: float = 0.0
    available: float = 0.0
    equity: float = 0.0
    currency: str = "GBP"
    updated_at: datetime = Field(default_factory=_utcnow)


class RiskDecision(BaseModel):
    """Result of RiskEngine.evaluate_entry."""

    allowed: bool
    size: float = 0.0                # approved £/pt stake (0 if blocked)
    risk_amount: float = 0.0         # £ at risk if stopped out
    reasons: list[str] = Field(default_factory=list)   # why blocked / adjusted
