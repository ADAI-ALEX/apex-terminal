"""Seed DEEP EUR/USD intraday history from Dukascopy (free, multi-year).

Yahoo caps 5m/15m at ~60 days, which is why the committed EURUSD_5m.csv only spans
~2 months. Dukascopy serves years of FX candles for free, letting us walk-forward
the scalper across many real regimes on the ACTUAL trade timeframe (not just 1h).

Writes EURUSD_<5m|15m>.csv in the backtester's schema:
    date, open, high, low, close, volume, fear_greed, vix, sentiment
The intraday exo columns (fear_greed/vix/sentiment) are set to 0.0 — they are not
available intraday from this source and the markov/scalper strategies do not use
them. (Daily EURUSD_D1.csv keeps its real exo.)

Run:  venv/Scripts/python.exe scripts/seed_dukascopy_eurusd.py [start_year]
"""
from __future__ import annotations

import csv
import datetime as dt
import sys
from pathlib import Path

import dukascopy_python as dk
from dukascopy_python.instruments import INSTRUMENT_FX_MAJORS_EUR_USD as EURUSD

DATA = Path(__file__).resolve().parents[1] / "apex" / "backtest" / "data"
_INTERVALS = {"5m": dk.INTERVAL_MIN_5, "15m": dk.INTERVAL_MIN_15}


def fetch_write(suffix: str, interval, start: dt.datetime, end: dt.datetime) -> None:
    print(f"fetching EURUSD {suffix} {start.date()}..{end.date()} ...", flush=True)
    df = dk.fetch(EURUSD, interval, dk.OFFER_SIDE_BID, start, end)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    out = DATA / f"EURUSD_{suffix}.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "open", "high", "low", "close", "volume",
                    "fear_greed", "vix", "sentiment"])
        for ts, row in df.iterrows():
            w.writerow([ts.isoformat(), f"{row.open:.5f}", f"{row.high:.5f}",
                        f"{row.low:.5f}", f"{row.close:.5f}", f"{row.volume:.2f}",
                        "0.0", "0.0", "0.0"])
    print(f"+ wrote {out.name}: {len(df)} bars {df.index[0]} -> {df.index[-1]}", flush=True)


if __name__ == "__main__":
    start_year = int(sys.argv[1]) if len(sys.argv) > 1 else 2023
    start = dt.datetime(start_year, 1, 1)
    end = dt.datetime(2026, 6, 5)
    for suffix, interval in _INTERVALS.items():
        try:
            fetch_write(suffix, interval, start, end)
        except Exception as exc:  # noqa: BLE001 - one-time seeding, report and continue
            print(f"! EURUSD {suffix} failed: {exc}", flush=True)
