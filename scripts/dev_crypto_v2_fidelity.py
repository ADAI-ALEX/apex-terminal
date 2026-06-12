"""Dev-only 1-MINUTE execution-fidelity replay for the Phase-5.2 4H champion.

The 4H backtest fills stops/targets intrabar against 4H highs/lows and books
FLAT (momentum-death) exits at the 4H close. This replays every champion trade
over the REAL 1m path (Binance perp seeds, 2025-01..2026-05 coverage) and asks:

  1. Would the stop/target have filled at a different price or earlier moment
     on the 1m path (incl. gap-through-stop fills at the 1m open)?
  2. What was the worst intratrade 1m adverse excursion in equity terms — does
     the 4H-marked daily-DD survive 1m-resolution marking?

Run:  venv/Scripts/python.exe scripts/dev_crypto_v2_fidelity.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

logger.remove()

from dev_crypto_v2 import build_h4, load_tf, run  # noqa: E402

from apex.backtest import dataset  # noqa: E402

#: Final V2 configuration (must mirror crypto_state_v2.py).
FINAL = dict(risk=2.8, z=0.9, flow=0.015, d1=4.5, d2=6.0, m1=0.6, m2=0.4)
BAR = timedelta(hours=4)


def main() -> None:
    code = build_h4(**FINAL)
    d = run(code, "BTCUSD", 240, "2025-01-01", None)
    trades = [t for t in d["trade_log"] if t["reason"] != "SCALE"]
    print(f"4H champion, 2025-01..2026-05 window: {len(trades)} trades, "
          f"ret {d['total_return_pct']:.2f}%  dDD {d['max_daily_dd_pct']:.2f}%")

    m1 = dataset.load("BTCUSD", 0, timeframe="1m")
    bars = m1.candles
    times = [c.time for c in bars]
    print(f"1m path: {len(bars)} bars ({times[0]:%Y-%m-%d} .. {times[-1]:%Y-%m-%d})\n")

    import bisect

    hdr = "%-17s %-5s %9s %9s %7s | %-5s %9s %7s %8s %8s" % (
        "opened", "rsn", "entry", "exit4H", "ret4H%", "rsn1m", "exit1m", "ret1m%",
        "dret%", "MAE_R")
    print(hdr)
    tot4 = tot1 = 0.0
    worst_mae = 0.0
    for t in trades:
        opened = datetime.fromisoformat(t["opened"]).replace(tzinfo=timezone.utc)
        closed = datetime.fromisoformat(t["closed"]).replace(tzinfo=timezone.utc)
        entry, stop, exit4 = t["entry"], t["stop"], t["exit"]
        risk_pts = abs(entry - stop)
        target = entry + 6.0 * risk_pts          # target_rr = 6 (long-only)
        # the entry fills at the END of the signal bar; replay from there to the
        # end of the exit bar
        t0, t1 = opened + BAR, closed + BAR
        i = bisect.bisect_left(times, t0)
        j = bisect.bisect_right(times, t1)
        exit1, rsn1 = None, None
        mae = 0.0                                # worst adverse excursion, in R
        for k in range(i, j):
            b = bars[k]
            mae = max(mae, (entry - b.low) / risk_pts if risk_pts else 0.0)
            if b.low <= stop:
                exit1, rsn1 = (min(b.open, stop), "SL")   # gap-through fills worse
                break
            if b.high >= target:
                exit1, rsn1 = (max(b.open, target), "TP")
                break
        if exit1 is None:
            exit1, rsn1 = exit4, t["reason"]     # close-based exit: same fill
        r4 = 100.0 * (exit4 - entry) / entry
        r1 = 100.0 * (exit1 - entry) / entry
        tot4 += r4
        tot1 += r1
        worst_mae = max(worst_mae, mae)
        print("%-17s %-5s %9.1f %9.1f %7.2f | %-5s %9.1f %7.2f %8.3f %8.2f" % (
            t["opened"][:16], t["reason"], entry, exit4, r4, rsn1, exit1, r1,
            r1 - r4, mae))
    print("\nsum price-return 4H %.2f%%  vs 1m-replay %.2f%%  (delta %.3f%%)"
          % (tot4, tot1, tot1 - tot4))
    print("worst 1m intratrade adverse excursion: %.2f R "
          "(equity hit at 2.8%% base risk ~= %.2f%%)" % (worst_mae, worst_mae * 2.8))


if __name__ == "__main__":
    main()
