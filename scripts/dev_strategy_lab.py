"""Dev-only strategy lab: backtest candidate custom strategies on the local data
and print win-rate / profit-factor / return / drawdown, so we can pick a robust,
high-win-rate default the way the video prescribes (optimize, prefer stable params).

Not committed as part of the app — a research harness.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root on path

from apex.backtest.runner import run_request
from apex.config import get_settings


class _Broker:
    mode = "PAPER"


def metrics(code: str, market: str, bars: int = 6000) -> dict:
    from apex.strategies import store
    store.save("labtmp", code)
    try:
        r = run_request(_Broker(), get_settings(), {"market": market, "strategy": "labtmp", "bars": bars})
    finally:
        store.delete("labtmp")
    return r


def show(name: str, code: str, markets: list[str], bars: int = 6000) -> None:
    print(f"\n=== {name} ===")
    print(f"{'mkt':8} {'trades':>6} {'win%':>6} {'PF':>6} {'ret%':>9} {'maxDD%':>7} {'exp%':>7} {'avgRR':>6}")
    for mk in markets:
        r = metrics(code, mk, bars)
        if r.get("error"):
            print(f"{mk:8} ERROR: {r['error']}")
            continue
        print(f"{mk:8} {r['trades']:>6} {r['win_rate']:>6} {r['profit_factor']:>6} "
              f"{r['total_return_pct']:>9} {r['max_total_dd_pct']:>7} {r['expectancy_pct']:>7} {r['avg_rr']:>6}")


CANDIDATES: dict[str, str] = {
    "C1_donchian_breakout": '''
upper, lower = donchian(20)
if close >= upper:
    signal = "BUY"
elif close <= lower:
    signal = "SELL"
else:
    signal = "HOLD"
''',
    "C2_rsi2_pullback_trend": '''
trend_up = close > sma(200) and sma(50) > sma(200)
trend_dn = close < sma(200) and sma(50) < sma(200)
r = rsi(2)
if position == 0:
    if trend_up and r < 10:
        signal = "BUY"
    elif trend_dn and r > 90:
        signal = "SELL"
    else:
        signal = "HOLD"
elif position == 1 and (r > 65 or close > sma(5)):
    signal = "FLAT"
elif position == -1 and (r < 35 or close < sma(5)):
    signal = "FLAT"
else:
    signal = "HOLD"
''',
    "C3_bollinger_meanrev_trend": '''
up = close > sma(200)
dn = close < sma(200)
u, m, l = bollinger(20, 2)
r = rsi(3)
if position == 0:
    if up and close < l and r < 15:
        signal = "BUY"
    elif dn and close > u and r > 85:
        signal = "SELL"
    else:
        signal = "HOLD"
elif position == 1 and close > m:
    signal = "FLAT"
elif position == -1 and close < m:
    signal = "FLAT"
else:
    signal = "HOLD"
''',
}


def rsi2_code(rsi_entry=10, trend_sma=200, exit_rsi=65, max_hold=10, rsi_len=2):
    return f'''
trend_up = close > sma({trend_sma}) and sma(50) > sma({trend_sma})
trend_dn = close < sma({trend_sma}) and sma(50) < sma({trend_sma})
r = rsi({rsi_len})
if position == 0:
    if trend_up and r < {rsi_entry}:
        signal = "BUY"
    elif trend_dn and r > {100 - rsi_entry}:
        signal = "SELL"
    else:
        signal = "HOLD"
elif position == 1 and (r > {exit_rsi} or close > sma(5) or bars_held > {max_hold}):
    signal = "FLAT"
elif position == -1 and (r < {100 - exit_rsi} or close < sma(5) or bars_held > {max_hold}):
    signal = "FLAT"
else:
    signal = "HOLD"
'''


def sweep_us500() -> None:
    print("\n### Stability sweep on US500 (RSI entry threshold) ###")
    print(f"{'rsi_entry':>9} {'trades':>6} {'win%':>6} {'PF':>6} {'ret%':>8} {'maxDD%':>7}")
    for thr in (5, 8, 10, 12, 15, 20):
        r = metrics(rsi2_code(rsi_entry=thr), "US500")
        print(f"{thr:>9} {r['trades']:>6} {r['win_rate']:>6} {r['profit_factor']:>6} {r['total_return_pct']:>8} {r['max_total_dd_pct']:>7}")
    print("\n### Stability sweep on US500 (max-hold bars) ###")
    print(f"{'max_hold':>9} {'trades':>6} {'win%':>6} {'PF':>6} {'ret%':>8} {'maxDD%':>7}")
    for mh in (4, 6, 8, 10, 15, 99):
        r = metrics(rsi2_code(max_hold=mh), "US500")
        print(f"{mh:>9} {r['trades']:>6} {r['win_rate']:>6} {r['profit_factor']:>6} {r['total_return_pct']:>8} {r['max_total_dd_pct']:>7}")


if __name__ == "__main__":
    markets = ["US500", "FTSE100", "EURUSD", "BTCUSD", "ETHUSD"]
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg == "sweep":
        sweep_us500()
    elif arg == "final":
        show("FINAL rsi2(entry=10,hold=8)", rsi2_code(rsi_entry=10, max_hold=8), markets)
    else:
        for name, code in CANDIDATES.items():
            if arg and arg not in name:
                continue
            show(name, code, markets)
