"""Seed 4-hour (240m) crypto CSVs by resampling the committed 1H perp seeds.

Fully offline and deterministic: reads ``apex/backtest/data/{KEY}_60m.csv``
(written by ``scripts/seed_binance_perp.py``) and aggregates UTC-aligned
4-hour buckets — OHLC the standard way, ``volume`` and ``delta`` (real
taker-flow) summed, ``macro``/``macro_slow`` taking the bucket's LAST value
(they are derived from completed daily closes, so this introduces no
look-ahead). Re-run this after any re-seed of the 1H data so the 240m series
never goes stale.

The 240m series is the home timeframe of ``crypto_state_v2.py`` (Phase 5.2).

Run:  venv/Scripts/python.exe scripts/seed_4h_resample.py
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "apex" / "backtest" / "data"

KEYS = ("BTCUSD", "ETHUSD")
BUCKET_S = 240 * 60

#: column -> aggregation ("sum" | "last") for the exogenous fields.
EXO_AGG = {"volume": "sum", "delta": "sum", "macro": "last", "macro_slow": "last"}


def resample(key: str) -> None:
    src = DATA_DIR / f"{key}_60m.csv"
    if not src.exists():
        print(f"{key}: no 60m seed at {src.name} — skipped")
        return
    out_rows: list[dict] = []
    cur: dict | None = None
    bucket = -1
    with src.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            ts = int(datetime.fromisoformat(row["date"]).replace(tzinfo=timezone.utc).timestamp())
            b = ts // BUCKET_S * BUCKET_S
            o, h, l, c = (float(row["open"]), float(row["high"]),
                          float(row["low"]), float(row["close"]))
            if cur is None or b != bucket:
                if cur is not None:
                    out_rows.append(cur)
                bucket = b
                cur = {"date": datetime.fromtimestamp(b, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                       "open": o, "high": h, "low": l, "close": c}
                for col, agg in EXO_AGG.items():
                    cur[col] = float(row.get(col) or 0.0)
            else:
                cur["high"] = max(cur["high"], h)
                cur["low"] = min(cur["low"], l)
                cur["close"] = c
                for col, agg in EXO_AGG.items():
                    v = float(row.get(col) or 0.0)
                    cur[col] = cur[col] + v if agg == "sum" else v
    if cur is not None:
        out_rows.append(cur)

    dest = DATA_DIR / f"{key}_240m.csv"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "open", "high", "low", "close", "volume", "delta",
                    "macro", "macro_slow"])
        for r in out_rows:
            w.writerow([r["date"], r["open"], r["high"], r["low"], r["close"],
                        round(r["volume"], 3), round(r["delta"], 3),
                        r["macro"], r["macro_slow"]])
    print(f"wrote {dest.name}: {len(out_rows)} bars "
          f"({out_rows[0]['date'][:10]} .. {out_rows[-1]['date'][:10]})")


if __name__ == "__main__":
    for key in KEYS:
        resample(key)
    print("done.")
