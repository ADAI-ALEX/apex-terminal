"""One-off diagnostic: does any AUCTION signal actually predict forward returns?

For each bar we read the live volume profile (POC/VAH/VAL) + CVD slope, classify
the bar's LOCATION (below value / in value / above value) and ORDER-FLOW state,
then measure the forward h-bar return. Buckets report mean forward return (bps),
the probability price is higher h bars later, and the sample size — so we can SEE
empirically whether to fade or follow each auction condition before coding it.

Run:  venv/Scripts/python.exe scripts/dev_auction_probe.py [nas100|us500|eurusd]
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

H = 6          # forward horizon (bars)
PROFILE = 120  # profile lookback
BINS = 24
STEP = 1


def probe(key: str) -> None:
    s = dataset.load(key, 0, timeframe="60m")
    cs = s.candles
    n = len(cs)
    buckets: dict[str, list[float]] = {}

    def add(name: str, fwd: float) -> None:
        buckets.setdefault(name, []).append(fwd)

    warm = PROFILE + 60
    for i in range(warm, n - H, STEP):
        win = cs[i - PROFILE - 1 : i + 1]
        ctx = _Indicators(win)
        vp = ctx.volume_profile(PROFILE, BINS)
        cv = ctx.cvd(20)
        c = cs[i].close
        if not (vp.width > 0) or c <= 0:
            continue
        win = cs[max(0, i - 60): i + 1]
        adx_v = ind.adx(win, 14) or 0.0
        atr_v = ind.atr(win, 14) or 0.0
        r2 = ind.rsi([x.close for x in win], 2) or 50.0
        fwd = 10000.0 * (cs[i + H].close - c) / c   # forward return in bps
        cv_up = cv > cv.prev
        below = c < vp.val
        ranging = adx_v < 20
        deep = atr_v > 0 and c < vp.val - 0.5 * atr_v

        if below and ranging:
            add("BELOW+ranging", fwd)
            if cv_up:
                add("BELOW+ranging+cvUp", fwd)
            if r2 < 10:
                add("BELOW+ranging+rsi2<10", fwd)
            if r2 < 5:
                add("BELOW+ranging+rsi2<5", fwd)
            if deep:
                add("BELOW+ranging+deep(.5atr)", fwd)
            if deep and r2 < 10:
                add("BELOW+ranging+deep+rsi2<10", fwd)
            if cv_up and r2 < 10:
                add("BELOW+ranging+cvUp+rsi2<10", fwd)
        # Also test the simple oversold dip regardless of value location.
        if ranging and r2 < 5:
            add("ranging+rsi2<5(any loc)", fwd)
        e200 = ind.ema([x.close for x in cs[max(0, i - 260):i + 1]], 200)
        if e200 and adx_v >= 22 and c > e200 and r2 < 10:
            add("uptrend+rsi2<10", fwd)

    print(f"\n=== {key} 60m — forward {H}-bar return by auction state (n bars={n}) ===")
    print("%-34s %7s %8s %8s" % ("bucket", "count", "mean_bps", "P(up)%"))
    for name in sorted(buckets):
        xs = buckets[name]
        if len(xs) < 40:
            continue
        mean = sum(xs) / len(xs)
        pup = 100.0 * sum(1 for x in xs if x > 0) / len(xs)
        print("%-34s %7d %8.2f %8.1f" % (name, len(xs), mean, pup))


def main() -> None:
    which = (sys.argv[1].lower() if len(sys.argv) > 1 else "nas100")
    key = {"nas100": "NAS100", "us500": "US500", "eurusd": "EURUSD"}.get(which, "NAS100")
    probe(key)


if __name__ == "__main__":
    main()
