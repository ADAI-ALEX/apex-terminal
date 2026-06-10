"""Seed DEEP crypto perpetual-futures history from the Binance public archive.

Downloads monthly USDT-M perp kline zips from ``data.binance.vision`` (no API
key needed) for BTCUSDT / ETHUSDT across 1h / 15m / 5m / 1m, and writes them
into the offline backtester's CSV format (``apex/backtest/data/{KEY}_{TF}.csv``).

Why perp klines and not spot/Yahoo: the Phase-5 thesis trades the *perpetual*
market (leveraged retail flow, liquidation cascades), and Binance perp klines
carry ``taker_buy_volume`` — the REAL aggressor-side order flow. We store the
per-bar taker delta (buy volume minus sell volume, base units) in a ``delta``
column so strategies can read true volume delta instead of the close-location
proxy. Existing shallow BTCUSD/ETHUSD intraday CSVs are backed up to ``.bak``.

Run:  venv/Scripts/python.exe scripts/seed_binance_perp.py [--quick]
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "apex" / "backtest" / "data"
CACHE_DIR = DATA_DIR / ".binance_cache"

BASE = "https://data.binance.vision/data/futures/um/monthly/klines"

#: archive timeframe -> on-disk file suffix (matches apex.backtest.dataset).
TF_SUFFIX = {"1h": "60m", "15m": "15m", "5m": "5m", "1m": "1m"}

#: Binance symbol -> backtester instrument key.
SYMBOLS = {"BTCUSDT": "BTCUSD", "ETHUSDT": "ETHUSD"}

#: (timeframe, first_month) — depth tuned to bar count: ~6.4y of 15m ≈ 225k bars,
#: 1m kept to the most recent 17 months (~745k bars) to stay tractable.
DEPTH = {"1h": "2020-01", "15m": "2020-01", "5m": "2023-01", "1m": "2025-01"}
LAST_MONTH = "2026-05"  # most recent complete month in the archive


def _months(first: str, last: str) -> list[str]:
    y, m = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    out = []
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _fetch(symbol: str, tf: str, month: str) -> Path | None:
    """Download one monthly zip into the cache (skip if cached). None on 404."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{symbol}-{tf}-{month}.zip"
    dest = CACHE_DIR / name
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = f"{BASE}/{symbol}/{tf}/{name}"
    try:
        with urlopen(url, timeout=60) as resp:
            blob = resp.read()
    except HTTPError as exc:
        if exc.code == 404:
            print(f"  missing (404): {name}")
            return None
        raise
    except URLError as exc:
        print(f"  RETRY-WORTHY network error on {name}: {exc}")
        return None
    dest.write_bytes(blob)
    return dest


def _rows_from_zip(path: Path) -> list[tuple[int, float, float, float, float, float, float]]:
    """Parse one kline zip -> [(open_ms, o, h, l, c, base_vol, taker_buy_base)]."""
    out = []
    with zipfile.ZipFile(path) as zf:
        with zf.open(zf.namelist()[0]) as fh:
            for line in io.TextIOWrapper(fh, encoding="utf-8"):
                parts = line.strip().split(",")
                if len(parts) < 10:
                    continue
                try:
                    ts = int(parts[0])
                except ValueError:
                    continue  # header row
                if ts > 10_000_000_000_000_000:   # microseconds
                    ts //= 1000
                elif ts < 100_000_000_000:        # seconds
                    ts *= 1000
                out.append((ts, float(parts[1]), float(parts[2]), float(parts[3]),
                            float(parts[4]), float(parts[5]), float(parts[9])))
    return out


def seed(symbol: str, key: str, tf: str, first_month: str) -> None:
    months = _months(first_month, LAST_MONTH)
    print(f"{symbol} {tf}: {len(months)} months ({first_month}..{LAST_MONTH})")
    with ThreadPoolExecutor(max_workers=12) as pool:
        paths = list(pool.map(lambda m: _fetch(symbol, tf, m), months))

    rows: list[tuple[int, float, float, float, float, float, float]] = []
    for p in paths:
        if p is not None:
            rows.extend(_rows_from_zip(p))
    rows.sort(key=lambda r: r[0])
    # de-duplicate on timestamp (overlapping months never happen, but be safe)
    dedup: list = []
    last_ts = -1
    for r in rows:
        if r[0] != last_ts:
            dedup.append(r)
            last_ts = r[0]

    # Walk-forward MACRO overlay: % distance of each bar's close to the 50-day
    # SMA of COMPLETED daily closes (days strictly before the bar's day). The
    # probe-proven regime gate — the 15m momentum edge only exists above it.
    # Live engines reproduce it from daily candles; 0.0 until 50 days exist.
    day_last: dict = {}
    for ts, _o, _h, _l, c, _v, _tb in dedup:
        day_last[datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).date()] = c

    out = DATA_DIR / f"{key}_{TF_SUFFIX[tf]}.csv"
    if out.exists():
        bak = out.with_suffix(".csv.bak")
        if not bak.exists():
            out.replace(bak)
            print(f"  backed up old {out.name} -> {bak.name}")
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "open", "high", "low", "close", "volume", "delta",
                    "macro", "macro_slow"])
        seen_days: list[float] = []
        cur_day = None
        for ts, o, h, l, c, vol, taker_buy in dedup:
            dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
            d = dt.date()
            if cur_day is None:
                cur_day = d
            elif d != cur_day:
                seen_days.append(day_last[cur_day])
                cur_day = d
            macro = macro_slow = 0.0
            if len(seen_days) >= 50:
                sma50 = sum(seen_days[-50:]) / 50.0
                macro = round(100.0 * (c / sma50 - 1.0), 3)
            if len(seen_days) >= 200:
                sma200 = sum(seen_days[-200:]) / 200.0
                macro_slow = round(100.0 * (c / sma200 - 1.0), 3)
            delta = 2.0 * taker_buy - vol     # taker buys minus taker sells
            w.writerow([dt.strftime("%Y-%m-%dT%H:%M:%S"), o, h, l, c,
                        round(vol, 3), round(delta, 3), macro, macro_slow])
    print(f"  wrote {out.name}: {len(dedup)} bars "
          f"({datetime.fromtimestamp(dedup[0][0]/1000, tz=timezone.utc):%Y-%m-%d} .. "
          f"{datetime.fromtimestamp(dedup[-1][0]/1000, tz=timezone.utc):%Y-%m-%d})")


if __name__ == "__main__":
    quick = "--quick" in sys.argv
    for sym, key in SYMBOLS.items():
        for tf, first in DEPTH.items():
            if quick and tf != "15m":
                continue
            seed(sym, key, tf, first)
    print("done.")
