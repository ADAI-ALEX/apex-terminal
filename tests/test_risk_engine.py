"""RiskEngine unit tests — the most safety-critical component."""

from __future__ import annotations

import pytest

from apex.config import Direction, get_settings
from apex.models import AccountSnapshot, Position, Signal
from apex.risk.risk_engine import RiskContext, RiskEngine


def _account(balance: float = 10_000.0) -> AccountSnapshot:
    return AccountSnapshot(balance=balance, available=balance, equity=balance)


def _signal(market: str = "FTSE100", entry: float = 100.0, stop: float = 80.0,
            target: float = 132.0) -> Signal:
    return Signal(market_key=market, epic=f"EPIC.{market}", strategy="ema_trend",
                  direction=Direction.BUY, entry=entry, stop=stop, target=target, target_rr=1.6)


def _position(market: str, entry: float = 100.0, stop: float = 70.0, size: float = 10.0) -> Position:
    return Position(deal_id=f"d-{market}", market_key=market, epic=f"EPIC.{market}",
                    direction=Direction.BUY, size=size, entry_price=entry, stop_price=stop,
                    target_price=entry + 30, current_price=entry)


@pytest.fixture
def engine() -> RiskEngine:
    return RiskEngine()


def test_happy_path_allows_and_sizes(engine):
    # 2% of £10k = £200 risk over a 20-pt stop → £10/pt.
    decision = engine.evaluate_entry(_signal(), RiskContext(account=_account()))
    assert decision.allowed
    assert decision.size == pytest.approx(10.0, abs=0.01)
    assert decision.risk_amount == pytest.approx(200.0, abs=0.5)


def test_daily_loss_limit_blocks(engine):
    ctx = RiskContext(account=_account(), daily_pnl_pct=-5.0)
    d = engine.evaluate_entry(_signal(), ctx)
    assert not d.allowed and "Daily loss limit" in d.reasons[0]


def test_weekly_halt_blocks(engine):
    ctx = RiskContext(account=_account(), weekly_halt=True)
    assert not engine.evaluate_entry(_signal(), ctx).allowed


def test_max_concurrent_positions_blocks(engine):
    ctx = RiskContext(account=_account(),
                      open_positions=[_position("US500"), _position("DAX40"), _position("EURUSD")])
    d = engine.evaluate_entry(_signal(), ctx)
    assert not d.allowed and "Max concurrent" in d.reasons[0]


def test_news_blackout_blocks(engine):
    assert not engine.evaluate_entry(_signal(), RiskContext(account=_account(), news_blackout=True)).allowed


def test_close_buffer_blocks(engine):
    assert not engine.evaluate_entry(_signal(), RiskContext(account=_account(), within_close_buffer=True)).allowed


def test_duplicate_market_blocks(engine):
    ctx = RiskContext(account=_account(), open_positions=[_position("FTSE100")])
    d = engine.evaluate_entry(_signal("FTSE100"), ctx)
    assert not d.allowed and "Already in" in d.reasons[0]


def test_consecutive_loss_throttle_halves_size(engine):
    ctx = RiskContext(account=_account(), consecutive_losses=4, trades_since_streak=0)
    d = engine.evaluate_entry(_signal(), ctx)
    assert d.allowed
    assert d.size == pytest.approx(5.0, abs=0.01)  # half of the £10/pt base


def test_total_open_risk_cap_blocks(engine):
    # Two open positions risking £300 each (3% + 3% = 6%); a new £200 → 8% > 6% cap.
    opens = [_position("US500", entry=100, stop=70, size=10),
             _position("DAX40", entry=100, stop=70, size=10)]
    ctx = RiskContext(account=_account(), open_positions=opens)
    d = engine.evaluate_entry(_signal("FTSE100"), ctx)
    assert not d.allowed
    assert any("Total open risk" in r for r in d.reasons)


def test_kill_switch_blocks(monkeypatch, engine):
    monkeypatch.setenv("TRADING_ENABLED", "false")
    get_settings.cache_clear()
    try:
        d = engine.evaluate_entry(_signal(), RiskContext(account=_account()))
        assert not d.allowed and "kill switch" in d.reasons[0]
    finally:
        monkeypatch.delenv("TRADING_ENABLED", raising=False)
        get_settings.cache_clear()


def test_overnight_close_logic(engine):
    from datetime import datetime, timezone
    pos = _position("FTSE100")
    pos.current_price = pos.entry_price + 5  # only +5pt, below 20pt keep threshold
    late = datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)
    assert engine.should_close_overnight(pos, late) is True
    pos.current_price = pos.entry_price + 50  # healthy profit → keep
    assert engine.should_close_overnight(pos, late) is False
