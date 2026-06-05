"""Dev-only research harness for the high-volume intraday scalper.

Backtests a parametrised regime-switching scalp on the local 5m/15m data and
prints FTMO-relevant metrics (trades, win%, PF, return, daily + total drawdown,
expectancy, and the Monte-Carlo pass/breach odds for a 10% target / 10% total
limit). Not part of the app — a harness like scripts/dev_strategy_lab.py.

Run:  venv/Scripts/python.exe scripts/dev_scalp_lab.py [sweep]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

logger.remove()

from apex.backtest.runner import run_request  # noqa: E402
from apex.config import get_settings  # noqa: E402
from apex.strategies import store  # noqa: E402


class _Broker:
    mode = "PAPER"


# ── the candidate strategy, parametrised ─────────────────────────────────────
DEFAULTS = dict(
    EMAF=20, EMAS=50, ADXR=20, ADXT=25, RSILO=5, RSIPB=15, REXIT=55,
    MAXHOLD=12, VOLK=2.5, BASE=0.5, DAYSTOP=2.5, DAYTGT=3.0, MAXTR=20, MAXDD=6.0,
)


def build(**kw) -> str:
    p = {**DEFAULTS, **kw}
    return '''
adx_v = adx(14)
ema_f = ema({EMAF})
ema_s = ema({EMAS})
up = ema_f > ema_s
dn = ema_f < ema_s
u, mid, l = bollinger(20, 2.0)
r = rsi(2)
a = atr(14)

wide = (high - low) > {VOLK} * a if (a and a > 0) else True
survival = dd_from_peak_pct >= {MAXDD}
day_locked = day_pnl_pct <= -{DAYSTOP} or day_pnl_pct >= {DAYTGT} or trades_today >= {MAXTR}

base = {BASE}
if consec_losses >= 4:
    base = base * 0.25
elif consec_losses >= 2:
    base = base * 0.5
risk = round(max(0.1, min(base, 0.7)), 2)

signal = "HOLD"
if survival:
    if position != 0:
        signal = "FLAT"
elif position == 0 and not day_locked and not wide:
    if adx_v < {ADXR}:
        if r < {RSILO} and close <= l:
            signal = "BUY"
        elif r > (100 - {RSILO}) and close >= u:
            signal = "SELL"
    elif adx_v >= {ADXT}:
        if up and r < {RSIPB} and close > ema_s:
            signal = "BUY"
        elif dn and r > (100 - {RSIPB}) and close < ema_s:
            signal = "SELL"
elif position == 1:
    if r > {REXIT} or bars_held >= {MAXHOLD}:
        signal = "FLAT"
elif position == -1:
    if r < (100 - {REXIT}) or bars_held >= {MAXHOLD}:
        signal = "FLAT"
'''.format(**p)


def run(code: str, market: str, minutes: int, bars: int) -> dict:
    store.save("scalptmp", code)
    try:
        return run_request(_Broker(), get_settings(), {
            "market": market, "strategy": "scalptmp", "bars": bars,
            "minutes": minutes, "source": "local",
            "target_pct": 10.0, "total_limit_pct": 10.0,
        })
    finally:
        store.delete("scalptmp")


HDR = "%-8s %3s %6s %6s %6s %8s %7s %7s %7s %6s %6s" % (
    "mkt", "tf", "trades", "win%", "PF", "ret%", "dDD%", "tDD%", "exp%", "MCpas", "MCbr")


def show(label: str, code: str, markets, tfs=(5, 15), bars=8000) -> None:
    print(f"\n=== {label} ===\n{HDR}")
    for mk in markets:
        for tf in tfs:
            r = run(code, mk, tf, bars)
            if r.get("error"):
                print("%-8s %3d  ERR %s" % (mk, tf, r["error"][:60]))
                continue
            mc = r.get("monte_carlo", {})
            print("%-8s %3d %6d %6.1f %6.2f %8.2f %7.2f %7.2f %7.3f %6s %6s" % (
                mk, tf, r["trades"], r["win_rate"], r["profit_factor"],
                r["total_return_pct"], r["max_daily_dd_pct"], r["max_total_dd_pct"],
                r["expectancy_pct"], mc.get("pass_prob_pct", "-"), mc.get("breach_prob_pct", "-")))


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    deep = ["EURUSD", "BTCUSD"]
    allmk = ["US500", "FTSE100", "EURUSD", "BTCUSD", "ETHUSD"]
    tune_mk = ["US500", "FTSE100", "EURUSD", "ETHUSD"]
    if arg == "sweep":
        configs = [
            ("MR-only base0.3", dict(ADXT=999, BASE=0.3)),
            ("MR-only base0.6", dict(ADXT=999, BASE=0.6)),
            ("MR-only base0.6 rsilo10", dict(ADXT=999, BASE=0.6, RSILO=10)),
            ("MR-only base0.6 daytgt99", dict(ADXT=999, BASE=0.6, DAYTGT=99)),
            ("with-trend base0.6", dict(BASE=0.6)),
        ]
        for label, kw in configs:
            show(label, build(**kw), tune_mk, tfs=(5,), bars=8000)
    elif arg == "full":
        show("DEFAULTS full", build(), allmk, tfs=(5, 15), bars=8000)
    else:
        show("DEFAULTS deep", build(), deep, tfs=(5, 15), bars=6000)
