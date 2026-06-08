"""Seed DEEP US500 (S&P 500) intraday history from Dukascopy (free, multi-year).

Yahoo caps 15m/5m at ~60 days, which is why the committed US500_15m.csv only spans
~85 days — far too short to validate a 15M strategy across regimes. Dukascopy serves
years of index candles for free, letting us walk-forward the auction engine over the
2022 bear, 2023 recovery, 2024-25 bull and the 2025 tariff shock on the ACTUAL trade
timeframe.

Overwrites US500_<15m|5m>.csv in the backtester's schema:
    date, open, high, low, close, volume, fear_greed, vix, sentiment
The intraday exo columns are 0.0 (not available intraday from this source; the
auction strategies do not use them).

Run:  venv/Scripts/python.exe scripts/seed_dukascopy_us500.py [start_year] [suffixes]
      e.g.  ... 2020 15m       (15m only, from 2020)
"""
from __future__ import annotations

import csv
import datetime as dt
import sys
from pathlib import Path

import dukascopy_python as dk
from dukascopy_python.instruments import INSTRUMENT_IDX_AMERICA_E_SANDP_500 as US500

DATA = Path(__file__).resolve().parents[1] / "apex" / "backtest" / "data"
_INTERVALS = {"5m": dk.INTERVAL_MIN_5, "15m": dk.INTERVAL_MIN_15}


def fetch_write(suffix: str, interval, start: dt.datetime, end: dt.datetime) -> None:
    print(f"fetching US500 {suffix} {start.date()}..{end.date()} ...", flush=True)
    df = dk.fetch(US500, interval, dk.OFFER_SIDE_BID, start, end)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df = df[(df.open > 0) & (df.close > 0)]
    out = DATA / f"US500_{suffix}.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "open", "high", "low", "close", "volume",
                    "fear_greed", "vix", "sentiment"])
        for ts, row in df.iterrows():
            w.writerow([ts.isoformat(), f"{row.open:.2f}", f"{row.high:.2f}",
                        f"{row.low:.2f}", f"{row.close:.2f}", f"{row.volume:.2f}",
                        "0.0", "0.0", "0.0"])
    print(f"+ wrote {out.name}: {len(df)} bars {df.index[0]} -> {df.index[-1]}", flush=True)


if __name__ == "__main__":
    start_year = int(sys.argv[1]) if len(sys.argv) > 1 else 2020
    suffixes = sys.argv[2].split(",") if len(sys.argv) > 2 else ["15m"]
    start = dt.datetime(start_year, 1, 1)
    end = dt.datetime(2026, 6, 5)
    for suffix in suffixes:
        try:
            fetch_write(suffix, _INTERVALS[suffix], start, end)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {suffix} failed: {exc}", flush=True)
    print("Done.", flush=True)
