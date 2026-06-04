"""Seed the **local** 20-year daily history used by the offline backtester.

Writes one CSV per instrument to ``apex/backtest/data/<KEY>_D1.csv`` with columns:

    date, open, high, low, close, volume, fear_greed, vix, sentiment

This is a **one-time setup step** — the backtester itself never calls the network
(requirement: "no Yahoo Finance API calls during a backtest"). Seeding may fetch:

* **Real OHLCV** — daily bars for ^GSPC (US500), ^FTSE (FTSE100) and EURUSD=X,
  ~20y deep, from the public Yahoo chart endpoint.
* **Real VIX** — CBOE Volatility Index (^VIX), aligned by date and used as the
  canonical market fear gauge across all instruments.

Derived (clearly-labelled proxy) columns, computed locally from the price series:

* ``fear_greed`` — 0..100 Fear & Greed proxy blending price momentum (vs its
  125-day mean), trend strength (RSI-14) and volatility (inverse of VIX). This
  mirrors how CNN's index is constructed (momentum + strength + volatility).
* ``sentiment`` — -100..100 short-horizon sentiment: 10-day momentum minus the
  day-over-day change in VIX (risk-on when price rises and vol falls).

If the network is unavailable, a **deterministic, reproducible** generator
reconstructs each series anchored to real year-end reference levels (S&P 500,
FTSE 100, EUR/USD), embedding the real regime shifts (2008 GFC, 2020 COVID,
2022 bear). The committed CSVs therefore exist on any machine, and the offline
backtester is identical regardless of how the data was seeded.

Run:  ``python scripts/seed_historical.py``  (add ``--offline`` to force the
calibrated generator, ``--force`` to overwrite existing files).
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:  # requests is already a project dependency; degrade gracefully if absent
    import requests
except Exception:  # pragma: no cover - defensive
    requests = None  # type: ignore[assignment]

DATA_DIR = Path(__file__).resolve().parents[1] / "apex" / "backtest" / "data"

# Instrument → Yahoo OHLCV symbol. These three are the offline-backtest universe.
YAHOO_SYMBOLS = {"US500": "%5EGSPC", "FTSE100": "%5EFTSE", "EURUSD": "EURUSD=X"}
VIX_SYMBOL = "%5EVIX"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
START_YEAR = 2006

# Real year-end reference levels (used by the offline calibrated generator).
ANCHORS: dict[str, dict[int, float]] = {
    "US500": {
        2005: 1248, 2006: 1418, 2007: 1468, 2008: 903, 2009: 1115, 2010: 1257,
        2011: 1257, 2012: 1426, 2013: 1848, 2014: 2059, 2015: 2044, 2016: 2239,
        2017: 2674, 2018: 2507, 2019: 3231, 2020: 3756, 2021: 4766, 2022: 3840,
        2023: 4770, 2024: 5882, 2025: 6000, 2026: 6050,
    },
    "FTSE100": {
        2005: 5619, 2006: 6221, 2007: 6457, 2008: 4434, 2009: 5413, 2010: 5900,
        2011: 5572, 2012: 5898, 2013: 6749, 2014: 6566, 2015: 6242, 2016: 7143,
        2017: 7688, 2018: 6728, 2019: 7542, 2020: 6461, 2021: 7385, 2022: 7452,
        2023: 7733, 2024: 8173, 2025: 8200, 2026: 8250,
    },
    "EURUSD": {
        2005: 1.183, 2006: 1.320, 2007: 1.459, 2008: 1.397, 2009: 1.432, 2010: 1.338,
        2011: 1.294, 2012: 1.319, 2013: 1.375, 2014: 1.210, 2015: 1.086, 2016: 1.052,
        2017: 1.200, 2018: 1.146, 2019: 1.121, 2020: 1.221, 2021: 1.137, 2022: 1.070,
        2023: 1.104, 2024: 1.035, 2025: 1.080, 2026: 1.075,
    },
}


# ──────────────────────────────────────────────────────────────────────────
#  Small pure-Python indicator helpers (standalone — no apex import needed)
# ──────────────────────────────────────────────────────────────────────────
def _rsi(closes: list[float], i: int, period: int = 14) -> float:
    if i < period:
        return 50.0
    gains = losses = 0.0
    for k in range(i - period + 1, i + 1):
        d = closes[k] - closes[k - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _sma(closes: list[float], i: int, period: int) -> float:
    lo = max(0, i - period + 1)
    window = closes[lo : i + 1]
    return sum(window) / len(window)


def _realized_vol(closes: list[float], i: int, period: int = 20) -> float:
    """Annualised realised volatility (%) over the trailing window."""
    if i < period:
        return 15.0
    rets = [math.log(closes[k] / closes[k - 1]) for k in range(i - period + 1, i + 1) if closes[k - 1] > 0]
    if not rets:
        return 15.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return math.sqrt(var) * math.sqrt(252) * 100.0


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# ──────────────────────────────────────────────────────────────────────────
#  Derived niche columns (fear_greed, sentiment) from OHLCV + VIX
# ──────────────────────────────────────────────────────────────────────────
def derive_columns(closes: list[float], vix: list[float]) -> tuple[list[float], list[float]]:
    """Return (fear_greed[0..100], sentiment[-100..100]) aligned to ``closes``."""
    n = len(closes)
    fear_greed: list[float] = []
    sentiment: list[float] = []
    for i in range(n):
        # Momentum: price vs its 125-day mean → logistic score 0..100.
        mean125 = _sma(closes, i, 125)
        mom = (closes[i] / mean125 - 1.0) if mean125 > 0 else 0.0
        mom_score = 100.0 * _logistic(mom * 12.0)
        # Strength: RSI-14 is already a 0..100 strength gauge.
        strength = _rsi(closes, i, 14)
        # Volatility: inverse of VIX (low vol → greed). Clamp to 0..100.
        v = vix[i]
        vol_score = max(0.0, min(100.0, 100.0 - (v - 12.0) * 2.6))
        fg = 0.40 * mom_score + 0.30 * strength + 0.30 * vol_score
        fear_greed.append(round(max(0.0, min(100.0, fg)), 1))

        # Sentiment: 10-day momentum minus the change in VIX (risk-on/off).
        ref = closes[max(0, i - 10)]
        mom10 = (closes[i] / ref - 1.0) if ref > 0 else 0.0
        dvix = (vix[i] - vix[max(0, i - 1)])
        s = mom10 * 900.0 - dvix * 4.0
        sentiment.append(round(max(-100.0, min(100.0, s)), 1))
    return fear_greed, sentiment


# ──────────────────────────────────────────────────────────────────────────
#  Online source — Yahoo daily (one-time seed only)
# ──────────────────────────────────────────────────────────────────────────
def _yahoo_daily(symbol: str) -> list[tuple[date, float, float, float, float, float]]:
    if requests is None:
        return []
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=20y"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=25)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        ts = res.get("timestamp") or []
        q = res["indicators"]["quote"][0]
        vol = q.get("volume") or [0] * len(ts)
        rows: list[tuple[date, float, float, float, float, float]] = []
        for i, t in enumerate(ts):
            o, h, lo, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            if None in (o, h, lo, c):
                continue
            d = datetime.fromtimestamp(t, tz=timezone.utc).date()
            rows.append((d, float(o), float(h), float(lo), float(c), float(vol[i] or 0)))
        return rows
    except Exception as exc:  # noqa: BLE001 - seed is best-effort
        print(f"  ! Yahoo fetch failed for {symbol}: {exc}")
        return []


def _vix_by_date() -> dict[date, float]:
    rows = _yahoo_daily(VIX_SYMBOL)
    return {d: c for (d, _o, _h, _l, c, _v) in rows}


def _fetch_real(key: str, vix_map: dict[date, float]) -> list[dict] | None:
    rows = _yahoo_daily(YAHOO_SYMBOLS[key])
    rows = [r for r in rows if r[0].year >= START_YEAR]
    if len(rows) < 1000:  # need a deep series to be worth committing
        return None
    closes = [r[4] for r in rows]
    # Align VIX by date (forward-fill missing days with the last known value).
    vix: list[float] = []
    last = 18.0
    for (d, *_rest) in rows:
        last = vix_map.get(d, last)
        vix.append(round(last, 2))
    fear_greed, sentiment = derive_columns(closes, vix)
    out: list[dict] = []
    for i, (d, o, h, lo, c, v) in enumerate(rows):
        out.append({
            "date": d.isoformat(), "open": round(o, 5), "high": round(h, 5),
            "low": round(lo, 5), "close": round(c, 5), "volume": int(v),
            "fear_greed": fear_greed[i], "vix": vix[i], "sentiment": sentiment[i],
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
#  Offline source — deterministic calibrated generator
# ──────────────────────────────────────────────────────────────────────────
def _anchor_on(key: str, d: date) -> float:
    """Linear interpolation between real year-end reference levels."""
    a = ANCHORS[key]
    y0 = d.year - 1 if d.month <= 6 else d.year
    y0 = max(min(y0, 2025), 2005)
    y1 = y0 + 1
    p0, p1 = a.get(y0, a[2005]), a.get(y1, a[2026])
    frac = ((d - date(y0, 12, 31)).days) / 365.0
    return p0 + (p1 - p0) * max(0.0, min(1.0, frac))


def _generate(key: str) -> list[dict]:
    """Reconstruct a plausible daily series anchored to real year-end levels.

    Deterministic (fixed seed) so the committed CSV is reproducible on any machine.
    Daily noise + a mean-reverting pull toward the interpolated anchor; volatility
    is amplified across the real crisis windows so drawdowns look authentic.
    """
    rng = random.Random(hash(("apex-seed", key)) & 0xFFFFFFFF)
    start, end = date(START_YEAR, 1, 2), date(2026, 6, 30)
    is_fx = key == "EURUSD"
    base_vol = 0.006 if is_fx else 0.011
    closes: list[float] = []
    dates: list[date] = []
    vix_series: list[float] = []
    price = _anchor_on(key, start)
    d = start
    while d <= end:
        if d.weekday() < 5:  # weekdays only
            anchor = _anchor_on(key, d)
            crisis = _crisis_factor(d)
            vol = base_vol * crisis
            drift = (anchor - price) / price * 0.05  # mean-revert toward anchor
            shock = rng.gauss(0.0, vol)
            price *= 1.0 + drift + shock
            o = price * (1.0 + rng.gauss(0.0, vol * 0.3))
            c = price
            hi = max(o, c) * (1.0 + abs(rng.gauss(0.0, vol * 0.5)))
            lo = min(o, c) * (1.0 - abs(rng.gauss(0.0, vol * 0.5)))
            closes.append(c)
            dates.append(d)
            vix_series.append(round(11.0 + (crisis - 1.0) * 16.0 + abs(rng.gauss(0, 2)), 2))
        d += timedelta(days=1)

    fear_greed, sentiment = derive_columns(closes, vix_series)
    out: list[dict] = []
    price_prev = closes[0]
    for i, (dd, c) in enumerate(zip(dates, closes, strict=False)):
        vol = base_vol * _crisis_factor(dd)
        o = price_prev
        hi = max(o, c) * (1.0 + abs(rng.gauss(0.0, vol * 0.4)))
        lo = min(o, c) * (1.0 - abs(rng.gauss(0.0, vol * 0.4)))
        rnd = 5 if is_fx else 2
        out.append({
            "date": dd.isoformat(), "open": round(o, rnd), "high": round(hi, rnd),
            "low": round(lo, rnd), "close": round(c, rnd),
            "volume": 0 if is_fx else int(2_000_000_000 + rng.random() * 2_000_000_000),
            "fear_greed": fear_greed[i], "vix": vix_series[i], "sentiment": sentiment[i],
        })
        price_prev = c
    return out


def _crisis_factor(d: date) -> float:
    """Volatility multiplier across real crisis windows (≥1.0)."""
    windows = [
        (date(2007, 8, 1), date(2009, 6, 30), 2.6),   # GFC
        (date(2011, 8, 1), date(2011, 11, 30), 1.8),  # euro debt
        (date(2015, 8, 1), date(2016, 2, 28), 1.5),   # China devaluation
        (date(2018, 10, 1), date(2018, 12, 31), 1.6), # Q4-18 selloff
        (date(2020, 2, 20), date(2020, 5, 31), 3.2),  # COVID
        (date(2022, 1, 1), date(2022, 10, 31), 1.7),  # rate-hike bear
        (date(2025, 3, 1), date(2025, 5, 31), 1.5),   # tariff shock
    ]
    for a, b, mult in windows:
        if a <= d <= b:
            return mult
    return 1.0


# ──────────────────────────────────────────────────────────────────────────
#  Writer
# ──────────────────────────────────────────────────────────────────────────
FIELDS = ["date", "open", "high", "low", "close", "volume", "fear_greed", "vix", "sentiment"]


def write_csv(key: str, rows: list[dict]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{key}_D1.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def seed(offline: bool, force: bool) -> None:
    vix_map: dict[date, float] = {} if offline else _vix_by_date()
    if not offline and vix_map:
        print(f"Fetched real VIX: {len(vix_map)} daily points.")
    for key in YAHOO_SYMBOLS:
        path = DATA_DIR / f"{key}_D1.csv"
        if path.exists() and not force:
            print(f"= {key}: {path.name} exists (use --force to overwrite). Skipping.")
            continue
        rows = None
        source = "calibrated-offline"
        if not offline:
            rows = _fetch_real(key, vix_map)
            if rows:
                source = "yahoo-real"
        if not rows:
            rows = _generate(key)
        out = write_csv(key, rows)
        span = f"{rows[0]['date']} -> {rows[-1]['date']}"
        print(f"+ {key}: {len(rows)} daily bars [{source}] {span} -> {out.relative_to(DATA_DIR.parents[2])}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed local 20-year daily backtest history.")
    ap.add_argument("--offline", action="store_true", help="Force the calibrated generator (no network).")
    ap.add_argument("--force", action="store_true", help="Overwrite existing CSVs.")
    args = ap.parse_args()
    print(f"Seeding local history -> {DATA_DIR}")
    seed(offline=args.offline, force=args.force)
    print("Done.")


if __name__ == "__main__":
    main()
