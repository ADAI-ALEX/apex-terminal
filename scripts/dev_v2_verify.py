"""One-shot verification: the SHIPPED crypto_state_v2.py file, through the real
production path (strategy store -> on-disk 240m CSV -> backtest engine), must
reproduce the Phase-5.2 harness result. Dev-only."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

logger.remove()

from apex.backtest import dataset
from apex.backtest.custom_runner import validate_code
from apex.backtest.engine import run_backtest
from apex.backtest.runner import LOCAL_BACKTEST_MARKETS
from apex.config import MARKETS, get_settings
from apex.strategies import store

strat = store.get("crypto_state_v2")
assert strat is not None, "store did not resolve crypto_state_v2"
ok, err = validate_code(strat.code)
assert ok, f"validate_code failed: {err}"
print(f"store: '{strat.label}' kind={strat.kind} ({len(strat.code)} chars) — validates OK")

s = dataset.load("BTCUSD", 0, timeframe=dataset.suffix_for(240))
print(f"dataset: BTCUSD 240m -> {len(s.candles)} bars "
      f"({s.candles[0].time:%Y-%m-%d} .. {s.candles[-1].time:%Y-%m-%d})")

st = get_settings()
r = run_backtest(
    s.candles, MARKETS.get("BTCUSD") or LOCAL_BACKTEST_MARKETS["BTCUSD"],
    starting_equity=100_000.0, risk_pct=st.risk.max_risk_per_trade_pct,
    atr_stop_mult=st.risk.atr_stop_multiplier, params=st.strategy, mc_runs=300,
    target_pct=10.0, total_limit_pct=9.0, rr=st.risk.default_rr,
    strategy={"name": "crypto_state_v2", "kind": "custom", "code": strat.code},
    exo=s.exo, cost_pct=0.12,
)
months = len(s.candles) * 240 / (60.0 * 24.0 * 30.44)
print(f"FULL 2020-26: trades={r.trades} win={r.win_rate}% PF={r.profit_factor} "
      f"ret={r.total_return_pct}% ({r.total_return_pct/months:.2f}%/mo) "
      f"dDD={r.max_daily_dd_pct}% tDD={r.max_total_dd_pct}% "
      f"MC={r.monte_carlo.get('pass_prob_pct')}%")
