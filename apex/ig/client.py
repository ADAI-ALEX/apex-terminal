"""IG client wrapper — the ONLY code path that talks to the broker.

Two interchangeable backends behind one :class:`Broker` protocol:

* :class:`IGBroker`   — real IG REST via the ``trading-ig`` library (DEMO or LIVE).
* :class:`PaperBroker` — synthetic random-walk candles + simulated fills. Used
  automatically when IG credentials are absent or ``trading-ig`` isn't installed,
  so the entire system (and the dashboard) runs end-to-end on a dev machine.

The heartbeat calls these synchronous methods via ``asyncio.to_thread`` so the
event loop is never blocked by network I/O.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Protocol

from loguru import logger

from apex.config import Direction, Market, Settings, get_settings
from apex.models import AccountSnapshot, Candle, Position, Signal, TradeRecord

# Map our candle minutes → IG resolution strings.
_IG_RESOLUTION = {1: "MINUTE", 5: "MINUTE_5", 15: "MINUTE_15", 30: "MINUTE_30", 60: "HOUR"}


class Broker(Protocol):
    mode: str

    def connect(self) -> None: ...
    def account(self) -> AccountSnapshot: ...
    def candles(self, epic: str, minutes: int, count: int) -> list[Candle]: ...
    def latest_price(self, epic: str) -> float: ...
    def positions(self) -> list[Position]: ...
    def open_position(self, signal: Signal, size: float) -> Position | None: ...
    def close_position(self, position: Position, reason: str) -> TradeRecord | None: ...
    def sentiment(self, epic: str) -> dict[str, float]: ...


def create_broker(settings: Settings | None = None) -> Broker:
    """Pick the right backend. Falls back to paper mode when not fully configured."""
    settings = settings or get_settings()
    if settings.has_ig_credentials and _trading_ig_available():
        logger.info("IG credentials present — using live IGBroker ({})", settings.ig_acc_type.value)
        return IGBroker(settings)
    logger.warning("No IG credentials / trading-ig missing — using PaperBroker (simulation).")
    return PaperBroker(settings)


def _trading_ig_available() -> bool:
    try:
        import trading_ig  # noqa: F401
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════
#  Live IG backend
# ══════════════════════════════════════════════════════════════════════════
class IGBroker:
    mode = "IG"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._svc = None  # lazily created IGService

    def connect(self) -> None:
        from trading_ig import IGService  # lazy import

        self._svc = IGService(
            self.s.ig_username,
            self.s.ig_password,
            self.s.ig_api_key,
            self.s.ig_acc_type.value.lower(),
            acc_number=self.s.ig_account_id or None,
        )
        self._svc.create_session()
        logger.info("IG session established ({}).", self.s.ig_acc_type.value)

    @property
    def svc(self):  # type: ignore[no-untyped-def]
        if self._svc is None:
            self.connect()
        return self._svc

    def account(self) -> AccountSnapshot:
        data = self.svc.fetch_accounts()
        row = data.iloc[0]
        return AccountSnapshot(
            balance=float(row.get("balance", 0.0)),
            available=float(row.get("available", 0.0)),
            equity=float(row.get("balance", 0.0)),
            currency=str(row.get("currency", "GBP")),
        )

    def candles(self, epic: str, minutes: int, count: int) -> list[Candle]:
        resolution = _IG_RESOLUTION.get(minutes, "MINUTE_5")
        resp = self.svc.fetch_historical_prices_by_epic(epic, resolution=resolution, numpoints=count)
        df = resp["prices"]
        out: list[Candle] = []
        for ts, row in df.iterrows():
            # IG returns bid/ask columns; use mid.
            o = (row[("bid", "Open")] + row[("ask", "Open")]) / 2
            h = (row[("bid", "High")] + row[("ask", "High")]) / 2
            low = (row[("bid", "Low")] + row[("ask", "Low")]) / 2
            c = (row[("bid", "Close")] + row[("ask", "Close")]) / 2
            vol = float(row.get(("last", "Volume"), 0) or 0)
            out.append(Candle(time=ts.to_pydatetime(), open=o, high=h, low=low, close=c, volume=vol))
        return out

    def latest_price(self, epic: str) -> float:
        snap = self.svc.fetch_market_by_epic(epic)["snapshot"]
        return (float(snap["bid"]) + float(snap["offer"])) / 2

    def positions(self) -> list[Position]:
        df = self.svc.fetch_open_positions()
        out: list[Position] = []
        for _, row in df.iterrows():
            epic = row.get(("market", "epic"), row.get("epic", ""))
            direction = Direction(row.get(("position", "direction"), "BUY"))
            out.append(Position(
                deal_id=str(row.get(("position", "dealId"), "")),
                market_key=_epic_to_key(epic),
                epic=epic,
                direction=direction,
                size=float(row.get(("position", "size"), 0.0)),
                entry_price=float(row.get(("position", "level"), 0.0)),
                stop_price=float(row.get(("position", "stopLevel"), 0.0) or 0.0),
                target_price=float(row.get(("position", "limitLevel"), 0.0) or 0.0),
                current_price=self.latest_price(epic),
            ))
        return out

    def open_position(self, signal: Signal, size: float) -> Position | None:
        resp = self.svc.create_open_position(
            currency_code="GBP",
            direction=signal.direction.value,
            epic=signal.epic,
            expiry="DFB",
            force_open=True,
            guaranteed_stop=False,
            order_type="MARKET",
            size=size,
            level=None,
            limit_level=round(signal.target, 2),
            stop_level=round(signal.stop, 2),
            limit_distance=None,
            stop_distance=None,
            quote_id=None,
            trailing_stop=False,
            trailing_stop_increment=None,
        )
        deal_id = resp.get("dealId", "")
        if resp.get("dealStatus") != "ACCEPTED":
            logger.error("IG rejected order for {}: {}", signal.market_key, resp.get("reason"))
            return None
        logger.info("Opened {} {} @ {} size £{}/pt (deal {})",
                    signal.direction.value, signal.market_key, signal.entry, size, deal_id)
        return Position(
            deal_id=deal_id, market_key=signal.market_key, epic=signal.epic,
            direction=signal.direction, size=size, entry_price=signal.entry,
            stop_price=signal.stop, target_price=signal.target, current_price=signal.entry,
            strategy=signal.strategy, confidence=signal.confidence,
        )

    def close_position(self, position: Position, reason: str) -> TradeRecord | None:
        opposite = "SELL" if position.direction is Direction.BUY else "BUY"
        resp = self.svc.close_open_position(
            deal_id=position.deal_id, direction=opposite, epic=position.epic,
            expiry="DFB", level=None, order_type="MARKET", quote_id=None, size=position.size,
        )
        exit_price = float(resp.get("level", position.current_price) or position.current_price)
        return _trade_record(position, exit_price, reason)

    def sentiment(self, epic: str) -> dict[str, float]:
        try:
            market_id = epic.split(".")[2]
            data = self.svc.fetch_client_sentiment_by_instrument(market_id)
            return {"long": float(data["longPositionPercentage"]),
                    "short": float(data["shortPositionPercentage"])}
        except Exception:
            return {"long": 50.0, "short": 50.0}


# ══════════════════════════════════════════════════════════════════════════
#  Paper backend (simulation)
# ══════════════════════════════════════════════════════════════════════════
_SEED_PRICES = {
    "IX.D.FTSE.DAILY.IP": 8200.0,
    "IX.D.SPTRD.DAILY.IP": 5300.0,
    "IX.D.DAX.DAILY.IP": 18300.0,
    "CS.D.EURUSD.MINI.IP": 1.0850,
    "CS.D.GBPUSD.MINI.IP": 1.2700,
}


class PaperBroker:
    """In-memory simulated broker with deterministic-ish random-walk candles."""

    mode = "PAPER"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._balance = 10_000.0
        self._positions: dict[str, Position] = {}
        self._rng = random.Random(42)
        self._last_price: dict[str, float] = dict(_SEED_PRICES)

    def connect(self) -> None:
        logger.info("PaperBroker ready (simulated £{:.0f} account).", self._balance)

    def account(self) -> AccountSnapshot:
        unrealised = sum(p.unrealised_pnl for p in self._positions.values())
        return AccountSnapshot(
            balance=round(self._balance, 2),
            available=round(self._balance - unrealised, 2),
            equity=round(self._balance + unrealised, 2),
        )

    def candles(self, epic: str, minutes: int, count: int) -> list[Candle]:
        """Generate a plausible random-walk history ending 'now'."""
        base = _SEED_PRICES.get(epic, 1000.0)
        vol = base * 0.0015  # ~0.15% per-candle volatility
        rng = random.Random(hash((epic, count)) & 0xFFFF)
        price = base
        now = datetime.now(timezone.utc)
        out: list[Candle] = []
        for i in range(count):
            drift = math.sin(i / 18.0) * vol * 0.6  # gentle cyclic trend
            step = rng.gauss(0, vol) + drift
            o = price
            c = max(price + step, 0.01)
            hi = max(o, c) + abs(rng.gauss(0, vol * 0.4))
            lo = min(o, c) - abs(rng.gauss(0, vol * 0.4))
            t = now - timedelta(minutes=minutes * (count - i))
            out.append(Candle(time=t, open=round(o, 4), high=round(hi, 4),
                              low=round(lo, 4), close=round(c, 4), volume=rng.randint(50, 500)))
            price = c
        self._last_price[epic] = out[-1].close
        return out

    def latest_price(self, epic: str) -> float:
        last = self._last_price.get(epic, _SEED_PRICES.get(epic, 1000.0))
        nudged = last + self._rng.gauss(0, last * 0.0005)
        self._last_price[epic] = nudged
        return round(nudged, 4)

    def positions(self) -> list[Position]:
        for p in self._positions.values():
            p.current_price = self.latest_price(p.epic)
        return list(self._positions.values())

    def open_position(self, signal: Signal, size: float) -> Position | None:
        deal_id = f"PAPER-{len(self._positions)}-{int(datetime.now().timestamp())}"
        pos = Position(
            deal_id=deal_id, market_key=signal.market_key, epic=signal.epic,
            direction=signal.direction, size=size, entry_price=signal.entry,
            stop_price=signal.stop, target_price=signal.target, current_price=signal.entry,
            strategy=signal.strategy, confidence=signal.confidence,
        )
        self._positions[deal_id] = pos
        logger.info("[PAPER] Opened {} {} @ {} size £{}/pt", signal.direction.value,
                    signal.market_key, signal.entry, size)
        return pos

    def close_position(self, position: Position, reason: str) -> TradeRecord | None:
        pos = self._positions.pop(position.deal_id, None)
        if pos is None:
            return None
        exit_price = position.current_price
        record = _trade_record(pos, exit_price, reason)
        self._balance += record.pnl
        logger.info("[PAPER] Closed {} ({}) P&L £{:.2f}", pos.market_key, reason, record.pnl)
        return record

    def sentiment(self, epic: str) -> dict[str, float]:
        long = round(self._rng.uniform(35, 65), 1)
        return {"long": long, "short": round(100 - long, 1)}


# ── shared helpers ─────────────────────────────────────────────────────────
def _trade_record(position: Position, exit_price: float, reason: str) -> TradeRecord:
    sign = 1.0 if position.direction is Direction.BUY else -1.0
    points = (exit_price - position.entry_price) * sign
    return TradeRecord(
        deal_id=position.deal_id, market_key=position.market_key, direction=position.direction,
        strategy=position.strategy, size=position.size, entry_price=position.entry_price,
        exit_price=exit_price, pnl=round(points * position.size, 2), points=round(points, 2),
        exit_reason=reason, confidence=position.confidence, opened_at=position.opened_at,
    )


def _epic_to_key(epic: str) -> str:
    from apex.config import MARKETS
    for key, mkt in MARKETS.items():
        if mkt.epic == epic:
            return key
    return epic
