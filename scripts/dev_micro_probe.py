"""Forward-return probe for 15M US500 microstructure — find what ACTUALLY predicts.

For each NY-session bar over the deep 6.4-year 15M set we read the intraday state
(VWAP deviation, position vs the opening range, prior-day sweep, trend) and measure
the forward H-bar return. Buckets report mean forward bps + P(up) + count, so we can
SEE whether the edge is momentum (continuation) or reversion BEFORE coding a strategy.

Run:  venv/Scripts/python.exe scripts/dev_micro_probe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

logger.remove()

from apex.backtest import dataset  # noqa: E402
from apex.backtest.custom_runner import _Indicators  # noqa: E402
from apex.indicators import engine as ind  # noqa: E402

H = 8          # forward horizon (bars; 8 x 15m = 2h)
STEP = 1


def probe(key: str = "US500") -> None:
    cs = dataset.load(key, 0, timeframe="15m").candles
    n = len(cs)
    buckets: dict[str, list[float]] = {}

    def add(name: str, fwd: float) -> None:
        buckets.setdefault(name, []).append(fwd)

    warm = 260
    for i in range(warm, n - H, STEP):
        bar = cs[i]
        h = bar.time.hour
        if not (14 <= h < 19):          # NY active session only (UTC)
            continue
        win = cs[i - 220: i + 1]
        ctx = _Indicators(win)
        a = ctx.atr(14)
        if not a or a <= 0:
            continue
        vw = float(ctx.vwap(40))
        orng = ctx.opening_range(13, 30, 60)
        pdr = ctx.prev_day_range()
        c = bar.close
        ema50 = float(ctx.ema(50))
        fwd = 10000.0 * (cs[i + H].close - c) / c

        dev = (c - vw) / a                       # VWAP deviation in ATRs
        up_trend = c > ema50

        # 1) VWAP deviation buckets (reversion vs momentum away from VWAP)
        db = ("<-2" if dev < -2 else "-2..-1" if dev < -1 else "-1..0" if dev < 0
              else "0..1" if dev < 1 else "1..2" if dev < 2 else ">2")
        add(f"vwapDev {db:>6}", fwd)

        # 2) Opening-range location
        if not (orng.width != orng.width) and float(orng.width) > 0:   # not NaN
            orh, orl = float(orng.high), float(orng.low)
            if c > orh:
                add("ORB above-high", fwd)
                add(f"ORB above-high trend={up_trend}", fwd)
            elif c < orl:
                add("ORB below-low", fwd)
                add(f"ORB below-low trend={up_trend}", fwd)
            else:
                add("ORB inside", fwd)

        # 3) Prior-day sweep
        if not (pdr.high != pdr.high):            # not NaN
            pdh, pdl = float(pdr.high), float(pdr.low)
            if c > pdh:
                add("sweep > PDH", fwd)
            elif c < pdl:
                add("sweep < PDL", fwd)

        # 4) VWAP-reclaim with trend (momentum) vs stretched-below (reversion)
        if dev < -1.5:
            add(f"stretched below VWAP trend={up_trend}", fwd)
        if dev > 1.5:
            add(f"stretched above VWAP trend={up_trend}", fwd)

    print(f"\n=== {key} 15M — forward {H}-bar ({H*15}min) return by intraday state (n={n}) ===")
    print("%-34s %8s %9s %8s" % ("bucket", "count", "mean_bps", "P(up)%"))
    for name in sorted(buckets):
        xs = buckets[name]
        if len(xs) < 200:
            continue
        mean = sum(xs) / len(xs)
        pup = 100.0 * sum(1 for x in xs if x > 0) / len(xs)
        print("%-34s %8d %9.2f %8.1f" % (name, len(xs), mean, pup))


if __name__ == "__main__":
    probe()
