"""Probe the conditional return structure of BTC/ETH perp 15m (Phase-5 R&D).

Measures, walk-forward-safely (all features trailing, all targets forward),
the mean forward return in basis points conditioned on candidate state reads:

  A. HMM regime (3-state Gaussian, monthly refit, forward-filtered)
  B. momentum: sign/size of trailing 8/24-bar returns (autocorrelation)
  C. REAL taker-flow pressure (flow_norm quintiles)
  D. 20-bar breakout events, by HMM state x flow agreement
  E. volatility contraction (stdev20/stdev96) -> forward |move| (breakout fuel)
  F. cascade bars (trailing 8-bar return < -2.5 sigma) -> snap-back geometry

Cost yardstick: a 0.12% round trip = 12 bps; a state is only tradable when its
conditional forward edge clears ~15 bps at the horizon you can hold.

Run:  venv/Scripts/python.exe scripts/dev_crypto_probe.py [BTCUSD] [15]
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

logger.remove()

from apex.backtest import dataset  # noqa: E402
from apex.backtest.custom_runner import _hmm_obs, fit_hmm, hmm_filter_step  # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else "BTCUSD"
TF = int(sys.argv[2]) if len(sys.argv) > 2 else 15

s = dataset.load(KEY, 0, timeframe=dataset.suffix_for(TF))
cs = s.candles
deltas = s.exo.get("delta", [0.0] * len(cs))
n = len(cs)
closes = [c.close for c in cs]
vols = [c.volume or 0.0 for c in cs]
print(f"{KEY} {TF}m: {n} bars {cs[0].time:%Y-%m-%d}..{cs[-1].time:%Y-%m-%d}")

# per-bar % returns
ret1 = [0.0] * n
for i in range(1, n):
    ret1[i] = 100.0 * (closes[i] / closes[i - 1] - 1.0) if closes[i - 1] else 0.0


def trail_ret(i: int, k: int) -> float:
    j = i - k
    return 100.0 * (closes[i] / closes[j] - 1.0) if j >= 0 and closes[j] else math.nan


def fwd_ret(i: int, k: int) -> float:
    j = i + k
    return 100.0 * (closes[j] / closes[i] - 1.0) if j < n and closes[i] else math.nan


# rolling flow_norm(20) and stdev ratios via prefix sums
pref_d = [0.0]
pref_v = [0.0]
for i in range(n):
    pref_d.append(pref_d[-1] + deltas[i])
    pref_v.append(pref_v[-1] + vols[i])


def flow_norm(i: int, k: int = 20) -> float:
    a = max(0, i - k + 1)
    v = pref_v[i + 1] - pref_v[a]
    return (pref_d[i + 1] - pref_d[a]) / v if v > 0 else math.nan


def stdev(i: int, k: int) -> float:
    a = max(0, i - k + 1)
    w = ret1[a : i + 1]
    m = sum(w) / len(w)
    return (sum((x - m) ** 2 for x in w) / len(w)) ** 0.5


# ── A. walk-forward HMM states (monthly refit, filtered every bar) ───────────
print("\nfitting walk-forward HMM (monthly refit)...")
H_WIN, H_REFIT = 1000, 2880
state = [None] * n       # (p_bull, p_bear, sig_cur, order_pos) per bar
params = None
probs = None
for i in range(n):
    if i >= H_WIN and (i % H_REFIT == 0 or params is None):
        obs = _hmm_obs(closes[i - H_WIN : i + 1], "ret")
        params = fit_hmm(obs, 3)
        probs = list(params[0])
        for x in obs:
            probs = hmm_filter_step(probs, params[1], params[2], params[3], x)
    elif params is not None:
        probs = hmm_filter_step(probs, params[1], params[2], params[3], ret1[i])
    if params is not None:
        mus, vrs = params[2], params[3]
        order = sorted(range(3), key=lambda k: mus[k])
        pred = [sum(probs[r] * params[1][r][c] for r in range(3)) for c in range(3)]
        cur = max(range(3), key=lambda k: probs[k])
        pos = 0 if cur == order[0] else 2 if cur == order[-1] else 1
        state[i] = (pred[order[-1]], pred[order[0]], vrs[cur] ** 0.5, pos)

WARM = H_WIN + 1


def bucket_report(title: str, rows: list[tuple[str, list[float]]]) -> None:
    print(f"\n-- {title}")
    for name, vals in rows:
        vals = [v for v in vals if not math.isnan(v)]
        if len(vals) < 30:
            print(f"  {name:34s} n={len(vals):6d}  (too few)")
            continue
        m = sum(vals) / len(vals)
        sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5
        t = m / (sd / math.sqrt(len(vals))) if sd > 0 else 0.0
        print(f"  {name:34s} n={len(vals):6d}  fwd {m*100:+7.1f} bps  t={t:+5.1f}")


# A: HMM edge buckets -> f8
rows = []
for lo, hi, nm in [(-1.0, -0.3, "edge<-0.3"), (-0.3, -0.1, "-0.3..-0.1"), (-0.1, 0.1, "-0.1..0.1"),
                   (0.1, 0.3, "0.1..0.3"), (0.3, 1.0, "edge>0.3")]:
    vals = [fwd_ret(i, 8) for i in range(WARM, n - 8)
            if state[i] and lo <= (state[i][0] - state[i][1]) < hi]
    rows.append((f"HMM {nm}", vals))
bucket_report("A. HMM one-step edge -> fwd 8-bar ret", rows)

# B: momentum autocorrelation
rows = []
for k, fk in [(8, 8), (24, 24), (96, 96)]:
    for sgn, nm in [(1, f"past{k}>+1sig"), (-1, f"past{k}<-1sig")]:
        vals = []
        for i in range(WARM, n - fk):
            tr = trail_ret(i, k)
            sg = stdev(i, 96) * math.sqrt(k)
            if not math.isnan(tr) and sg > 0 and sgn * tr > sg:
                vals.append(sgn * fwd_ret(i, fk))
        rows.append((f"{nm} -> fwd{fk} (signed)", vals))
bucket_report("B. momentum: extreme trailing move -> same-sign fwd ret", rows)

# C: flow_norm quintiles -> f8
fl = [(flow_norm(i), i) for i in range(WARM, n - 8)]
fl = [(f, i) for f, i in fl if not math.isnan(f)]
fl.sort()
q = len(fl) // 5
rows = []
for k in range(5):
    seg = fl[k * q : (k + 1) * q]
    rows.append((f"flow_norm Q{k+1} [{seg[0][0]:+.3f}..{seg[-1][0]:+.3f}]",
                 [fwd_ret(i, 8) for _, i in seg]))
bucket_report("C. flow_norm(20) quintile -> fwd 8-bar ret", rows)

# D: 20-bar breakout events by HMM state + flow agreement
rows = []
hi20 = [max(c.high for c in cs[max(0, i - 20) : i]) if i > 0 else math.inf for i in range(n)]
lo20 = [min(c.low for c in cs[max(0, i - 20) : i]) if i > 0 else -math.inf for i in range(n)]
for nm, cond in [
    ("brk UP, HMM bull, flow>0", lambda i: closes[i] > hi20[i] and state[i][3] == 2 and flow_norm(i) > 0),
    ("brk UP, HMM bull, flow<0", lambda i: closes[i] > hi20[i] and state[i][3] == 2 and flow_norm(i) <= 0),
    ("brk UP, HMM bear", lambda i: closes[i] > hi20[i] and state[i][3] == 0),
    ("brk DN, HMM bear, flow<0", lambda i: closes[i] < lo20[i] and state[i][3] == 0 and flow_norm(i) < 0),
    ("brk DN, HMM bear, flow>0", lambda i: closes[i] < lo20[i] and state[i][3] == 0 and flow_norm(i) >= 0),
    ("brk DN, HMM bull", lambda i: closes[i] < lo20[i] and state[i][3] == 2),
]:
    sgn = 1 if "UP" in nm else -1
    vals = [sgn * fwd_ret(i, 16) for i in range(WARM, n - 16) if state[i] and cond(i)]
    rows.append((nm + " -> fwd16 signed", vals))
bucket_report("D. 20-bar breakouts x state x flow", rows)

# E: vol contraction -> forward absolute move (fuel) + breakout follow-through
rows = []
for nm, lo, hi in [("squeeze sd20/sd96<0.6", 0.0, 0.6), ("normal 0.6-1.4", 0.6, 1.4),
                   ("expanded >1.4", 1.4, 99.0)]:
    vals = [abs(fwd_ret(i, 16)) for i in range(WARM, n - 16)
            if stdev(i, 96) > 0 and lo <= stdev(i, 20) / stdev(i, 96) < hi]
    rows.append((nm + " -> |fwd16|", vals))
bucket_report("E. vol contraction -> fwd 16-bar |move| (bps)", rows)

# F: cascades: trailing 8-bar ret < -2.5 * sigma8 -> fwd 8/24 + flow split
rows = []
casc = []
for i in range(WARM, n - 24):
    tr = trail_ret(i, 8)
    sg = stdev(i, 96) * math.sqrt(8)
    if not math.isnan(tr) and sg > 0 and tr < -2.5 * sg:
        casc.append(i)
rows.append(("cascade -> fwd8", [fwd_ret(i, 8) for i in casc]))
rows.append(("cascade -> fwd24", [fwd_ret(i, 24) for i in casc]))
rows.append(("cascade, flow recovering", [fwd_ret(i, 24) for i in casc if flow_norm(i, 4) > flow_norm(i, 20)]))
rows.append(("cascade, flow still selling", [fwd_ret(i, 24) for i in casc if flow_norm(i, 4) <= flow_norm(i, 20)]))
rows.append(("UP-cascade -> fwd24 (mirror)", [
    fwd_ret(i, 24) for i in range(WARM, n - 24)
    if stdev(i, 96) > 0 and trail_ret(i, 8) > 2.5 * stdev(i, 96) * math.sqrt(8)]))
bucket_report("F. liquidation cascades (8-bar < -2.5 sigma)", rows)

# G. INTERSECTIONS: long momentum x flow x HMM (the candidate trade states)
sma480 = [math.nan] * n
run = 0.0
for i in range(n):
    run += closes[i]
    if i >= 480:
        run -= closes[i - 480]
        sma480[i] = run / 480.0


def mom_ok(i: int, k: int, mult: float = 1.0) -> bool:
    tr = trail_ret(i, k)
    sg = stdev(i, 96) * math.sqrt(k)
    return not math.isnan(tr) and sg > 0 and tr > mult * sg


rows = []
rows.append(("mom24 & flow>0.03 -> fwd24", [
    fwd_ret(i, 24) for i in range(WARM, n - 24) if mom_ok(i, 24) and flow_norm(i) > 0.03]))
rows.append(("mom24 & flow>0.03 & hmmB -> fwd24", [
    fwd_ret(i, 24) for i in range(WARM, n - 24)
    if mom_ok(i, 24) and flow_norm(i) > 0.03 and state[i] and state[i][0] > state[i][1]]))
rows.append(("mom96 & flow>0 -> fwd24", [
    fwd_ret(i, 24) for i in range(WARM, n - 24) if mom_ok(i, 96) and flow_norm(i) > 0.0]))
rows.append(("mom96 & flow>0 -> fwd96", [
    fwd_ret(i, 96) for i in range(WARM, n - 96) if mom_ok(i, 96) and flow_norm(i) > 0.0]))
rows.append(("mom96 & pullback8<0 -> fwd96", [
    fwd_ret(i, 96) for i in range(WARM, n - 96) if mom_ok(i, 96) and trail_ret(i, 8) < 0]))
rows.append(("mom96 & pull8<0 & flow>0 -> fwd96", [
    fwd_ret(i, 96) for i in range(WARM, n - 96)
    if mom_ok(i, 96) and trail_ret(i, 8) < 0 and flow_norm(i) > 0.0]))
rows.append(("mom96&24 & flow>0.03 -> fwd96", [
    fwd_ret(i, 96) for i in range(WARM, n - 96)
    if mom_ok(i, 96) and mom_ok(i, 24) and flow_norm(i) > 0.03]))
rows.append(("mom96 & >sma480 & hmmB -> fwd96", [
    fwd_ret(i, 96) for i in range(WARM, n - 96)
    if mom_ok(i, 96) and not math.isnan(sma480[i]) and closes[i] > sma480[i]
    and state[i] and state[i][0] > state[i][1]]))
rows.append(("mom96 x2sig & flow>0.03 -> fwd96", [
    fwd_ret(i, 96) for i in range(WARM, n - 96) if mom_ok(i, 96, 2.0) and flow_norm(i) > 0.03]))
bucket_report("G. intersection states (LONG candidates)", rows)
print("\ndone.")
