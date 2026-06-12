"""apex_mt5 — shared MT5 live-execution engine for the Apex V4 Institutional stack.

Runs inside the Windows Python under the ``~/.mt5`` Wine prefix on the VM,
attached to the FTMO MT5 terminal in the same prefix.

Fidelity contract: every indicator here is a line-for-line port of the Apex
backtest engine (``apex/indicators/engine.py`` + ``apex/backtest/custom_runner.py``)
so live signals match the walk-forward-validated configurations:
  * ATR / RSI / ADX use Wilder smoothing; EMA is SMA-seeded.
  * volume_profile(): uniform spread of each bar's volume across [low, high],
    POC = heaviest bin, value area grown to 70% by heavier neighbour.
  * cvd(): close-location-value x volume proxy.
Python owns ALL order execution. Hard stops ride INSIDE the order payload
(``sl``/``tp`` on the deal request), never in-memory only.
"""
from __future__ import annotations

import json
import logging
import math
import sys
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, NamedTuple, Optional, Sequence

import os as _os

# Execution backend seam: "bridge" (default) = file protocol to ApexBridge.mq5
# via native Linux Python; "native" = the real MetaTrader5 package (Windows /
# working-Wine hosts only — its IPC is broken under Wine on the Oracle VM).
if _os.environ.get("APEX_MT5_MODE", "bridge").lower() == "native":
    import MetaTrader5 as mt5  # type: ignore[import-not-found]
else:
    import mt5_filebridge as mt5  # type: ignore[no-redef]

NAN = float("nan")


def isnan(x: float) -> bool:
    """NaN check that also treats None as missing."""
    return x is None or (isinstance(x, float) and math.isnan(x))


# ──────────────────────────────────────────────────────────────────────────
#  .env loading (no hardcoded credentials — Hard Rule)
# ──────────────────────────────────────────────────────────────────────────
def load_env(path: Optional[Path] = None) -> dict[str, str]:
    """Parse ``.env`` next to the scripts (KEY=VALUE, ``#`` comments).

    Real process environment variables override file values.
    """
    import os

    p = path or Path(__file__).resolve().parent / ".env"
    out: dict[str, str] = {}
    if p.exists():
        for raw in p.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    for k, v in os.environ.items():
        out[k] = v
    return out


def env_bool(env: dict[str, str], key: str, default: bool = False) -> bool:
    """Read a boolean env flag ('1'/'true'/'yes' → True)."""
    raw = env.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ──────────────────────────────────────────────────────────────────────────
#  Candles + indicator ports (Wilder conventions — match apex/indicators)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Candle:
    """One closed OHLCV bar; ``time`` is the bar OPEN time in UTC."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def sma(values: Sequence[float], period: int) -> float:
    if len(values) < period or period <= 0:
        return NAN
    return sum(values[-period:]) / period


def ema(values: Sequence[float], period: int) -> float:
    """SMA-seeded EMA (matches apex.indicators.engine.ema_series)."""
    if len(values) < period or period <= 0:
        return NAN
    k = 2.0 / (period + 1.0)
    out = sum(values[:period]) / period
    for v in values[period:]:
        out = v * k + out * (1.0 - k)
    return out


def rsi(values: Sequence[float], period: int = 14) -> float:
    """Wilder RSI."""
    if len(values) < period + 1:
        return NAN
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(delta, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-delta, 0.0)) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))


def atr(candles: Sequence[Candle], period: int = 14) -> float:
    """Wilder ATR."""
    if len(candles) < period + 1:
        return NAN
    trs: list[float] = []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        trs.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))
    out = sum(trs[:period]) / period
    for tr in trs[period:]:
        out = (out * (period - 1) + tr) / period
    return out


def adx(candles: Sequence[Candle], period: int = 14) -> float:
    """Wilder ADX (port of apex.indicators.engine.adx)."""
    if len(candles) < 2 * period + 1:
        return NAN
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    trs: list[float] = []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        up = c.high - p.high
        down = p.low - c.low
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        trs.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))

    def _smooth(seq: list[float]) -> list[float]:
        out = [sum(seq[:period])]
        for v in seq[period:]:
            out.append(out[-1] - out[-1] / period + v)
        return out

    sm_tr, sm_p, sm_m = _smooth(trs), _smooth(plus_dm), _smooth(minus_dm)
    dx: list[float] = []
    for tr_v, p_v, m_v in zip(sm_tr, sm_p, sm_m):
        if tr_v == 0:
            continue
        dip = 100.0 * p_v / tr_v
        dim = 100.0 * m_v / tr_v
        den = dip + dim
        dx.append(0.0 if den == 0 else 100.0 * abs(dip - dim) / den)
    if len(dx) < period:
        return NAN
    a = sum(dx[:period]) / period
    for v in dx[period:]:
        a = (a * (period - 1) + v) / period
    return a


def roc(values: Sequence[float], n: int) -> float:
    """Close-to-close % return over ``n`` bars."""
    if len(values) <= n:
        return NAN
    base = values[-1 - n]
    return 100.0 * (values[-1] - base) / base if base else NAN


class VProfile(NamedTuple):
    poc: float
    vah: float
    val: float
    lvn: float
    width: float


def volume_profile(candles: Sequence[Candle], period: int = 120, bins: int = 30) -> VProfile:
    """Volume-by-price auction map — exact port of custom_runner.volume_profile."""
    bars = candles[-period:] if period > 0 else list(candles)
    if len(bars) < 3:
        return VProfile(NAN, NAN, NAN, NAN, NAN)
    lo = min(b.low for b in bars)
    hi = max(b.high for b in bars)
    if hi <= lo:
        return VProfile(lo, lo, lo, lo, 0.0)
    nb = max(4, int(bins))
    step = (hi - lo) / nb
    vol = [0.0] * nb
    for b in bars:
        i0 = max(0, min(nb - 1, int((max(lo, b.low) - lo) / step)))
        i1 = max(0, min(nb - 1, int((min(hi, b.high) - lo) / step)))
        w = (b.volume or 0.0) or 1.0
        share = w / (i1 - i0 + 1)
        for k in range(i0, i1 + 1):
            vol[k] += share
    total = sum(vol)
    if total <= 0:
        mid = (hi + lo) / 2.0
        return VProfile(mid, hi, lo, mid, hi - lo)
    poc_i = max(range(nb), key=lambda k: vol[k])
    lvn_i = min(range(nb), key=lambda k: vol[k])
    lo_i = hi_i = poc_i
    captured = vol[poc_i]
    target = 0.70 * total
    while captured < target and (lo_i > 0 or hi_i < nb - 1):
        below = vol[lo_i - 1] if lo_i > 0 else -1.0
        above = vol[hi_i + 1] if hi_i < nb - 1 else -1.0
        if above >= below:
            hi_i += 1
            captured += vol[hi_i]
        else:
            lo_i -= 1
            captured += vol[lo_i]
    return VProfile(
        lo + (poc_i + 0.5) * step,
        lo + (hi_i + 1) * step,
        lo + lo_i * step,
        lo + (lvn_i + 0.5) * step,
        (hi_i - lo_i + 1) * step,
    )


def cvd_sum(candles: Sequence[Candle]) -> float:
    """Sum of per-bar close-location-value × volume deltas (CVD proxy)."""
    d = 0.0
    for b in candles:
        rng = b.high - b.low
        if rng <= 0:
            continue
        clv = (2.0 * b.close - b.high - b.low) / rng
        d += clv * ((b.volume or 0.0) or 1.0)
    return d


def cvd(candles: Sequence[Candle], period: int = 20) -> float:
    return cvd_sum(candles[-period:])


def cvd_prev(candles: Sequence[Candle], period: int = 20) -> float:
    """CVD of the window ending one bar earlier (the snippet's ``.prev``)."""
    return cvd_sum(candles[:-1][-period:]) if len(candles) > 1 else NAN


def flow_norm_clv(candles: Sequence[Candle], period: int = 20) -> float:
    """CLV-proxy flow_norm: net CVD / total volume over ``period``, in [−1, +1].

    Live stand-in for the seed's real Binance taker-flow imbalance; strategies
    should prefer a real taker feed when one is reachable.
    """
    bars = candles[-period:]
    vol = sum((b.volume or 0.0) for b in bars)
    if vol <= 0:
        return NAN
    return cvd_sum(bars) / vol


def cvd_divergence(candles: Sequence[Candle], lookback: int = 12) -> int:
    """Regular CVD divergence (+1 bullish / −1 bearish / 0) — runner port."""
    bars = candles[-lookback:]
    n = len(bars)
    if n < 6:
        return 0
    cum = 0.0
    line: list[float] = []
    for b in bars:
        rng = b.high - b.low
        clv = (2.0 * b.close - b.high - b.low) / rng if rng > 0 else 0.0
        cum += clv * ((b.volume or 0.0) or 1.0)
        line.append(cum)
    half = n // 2
    lo_old = min(range(0, half), key=lambda k: bars[k].low)
    lo_new = min(range(half, n), key=lambda k: bars[k].low)
    if bars[lo_new].low < bars[lo_old].low and line[lo_new] > line[lo_old]:
        return 1
    hi_old = max(range(0, half), key=lambda k: bars[k].high)
    hi_new = max(range(half, n), key=lambda k: bars[k].high)
    if bars[hi_new].high > bars[hi_old].high and line[hi_new] < line[hi_old]:
        return -1
    return 0


# ──────────────────────────────────────────────────────────────────────────
#  Strategy contract
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class Ctx:
    """Bar-close snapshot handed to the strategy — mirrors the backtest DSL vars."""

    bars: list[Candle]
    position: int            # 0 flat / 1 long
    bars_held: int
    bars_since_scale: int    # −1 until the scale stage fills; 1 on first close after
    equity: float
    day_pnl_pct: float
    trades_today: int
    consec_losses: int
    dd_from_peak_pct: float
    total_pnl_pct: float
    hour_utc: int            # open hour (UTC) of the just-closed bar


@dataclass
class Decision:
    """Strategy output — the engine turns this into orders. BUY fields mirror
    the runner's sizing contract: stop = ``stop_dist`` price units below entry,
    TP at ``target_rr`` multiples of the stop distance, optional one-time
    partial bank at ``scale_at`` (+ break-even + trail)."""

    signal: str = "HOLD"     # HOLD | BUY | FLAT
    risk_pct: float = 1.0
    stop_dist: float = 0.0
    target_rr: float = 0.0   # 0 → no TP
    scale_at: float = 0.0    # 0 → no scale stage
    scale_frac: float = 0.0
    scale_be: bool = False
    trail_dist: float = 0.0
    reason: str = ""


@dataclass
class EngineConfig:
    name: str
    symbol: str
    timeframe: int                 # mt5.TIMEFRAME_*
    magic: int
    warmup_bars: int = 400
    poll_seconds: float = 10.0
    server_utc_offset_h: int = 3   # FTMO server (EET, DST) vs UTC
    deviation_points: int = 50
    login: int = 0
    password: str = ""
    server: str = ""
    terminal_path: str = ""
    watchdog_days: int = 0         # >0 → keep-alive nudge after N idle days (one leg only)


# ──────────────────────────────────────────────────────────────────────────
#  Engine
# ──────────────────────────────────────────────────────────────────────────
class Mt5Engine:
    """Owns the MT5 connection, governor state and ALL order execution."""

    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg
        self.log = self._mk_logger(cfg.name)
        self.state_path = Path(__file__).resolve().parent / f"{cfg.name}_state.json"
        self.state: dict = self._load_state()
        self._last_closed_bar = 0

    # ── infra ─────────────────────────────────────────────────────────
    def _mk_logger(self, name: str) -> logging.Logger:
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        fh = logging.FileHandler(Path(__file__).resolve().parent / f"{name}.log", encoding="utf-8")
        fh.setFormatter(fmt)
        lg.addHandler(sh)
        lg.addHandler(fh)
        return lg

    def _load_state(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception:
                self.log.warning("state file unreadable — starting fresh")
        return {}

    def _save_state(self) -> None:
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def connect(self) -> None:
        """Attach to the RUNNING terminal and log in to the FTMO account.

        BARE attach (no ``path``) is the primary mode. With ``path`` the lib
        spawns its own terminal and KILLS it when the IPC window expires —
        on a 1GB VM the terminal boots slower than any timeout, creating a
        perpetual spawn/kill loop (observed as repeated bare 'started' banners
        in the terminal journal). ``launch_all.sh`` pre-boots ONE shared
        terminal; engines only ever attach to it.
        """
        kwargs = dict(login=self.cfg.login, password=self.cfg.password,
                      server=self.cfg.server, timeout=180_000)
        ok = False
        last: object = None
        for attempt in range(1, 7):
            ok = mt5.initialize(**kwargs)          # bare attach — never spawns
            if ok:
                break
            last = mt5.last_error()
            self.log.warning("attach attempt %d/6 failed: %s — retry in 30s",
                             attempt, last)
            _time.sleep(30)
        if not ok and self.cfg.terminal_path:
            self.log.warning("bare attach exhausted — last resort: spawn via path")
            ok = mt5.initialize(self.cfg.terminal_path, **kwargs)
        if not ok:
            raise RuntimeError(f"mt5.initialize failed after retries: {last}")
        if not mt5.symbol_select(self.cfg.symbol, True):
            raise RuntimeError(f"symbol_select({self.cfg.symbol}) failed: {mt5.last_error()}")
        acc = mt5.account_info()
        if acc is None:
            raise RuntimeError(f"account_info unavailable: {mt5.last_error()}")
        self.log.info(
            "connected: account=%s server=%s balance=%.2f equity=%.2f symbol=%s",
            acc.login, acc.server, acc.balance, acc.equity, self.cfg.symbol,
        )
        if "initial_equity" not in self.state:
            self.state["initial_equity"] = acc.equity
            self.state["peak_equity"] = acc.equity
            self._save_state()

    # ── data ──────────────────────────────────────────────────────────
    def _tf_seconds(self) -> int:
        return {
            mt5.TIMEFRAME_M15: 900,
            mt5.TIMEFRAME_H1: 3600,
            mt5.TIMEFRAME_H4: 14400,
            mt5.TIMEFRAME_D1: 86400,
        }.get(self.cfg.timeframe, 3600)

    def _to_utc(self, server_epoch: int) -> datetime:
        return datetime.fromtimestamp(
            server_epoch - self.cfg.server_utc_offset_h * 3600, tz=timezone.utc
        )

    def closed_bars(self, symbol: str, timeframe: int, count: int) -> list[Candle]:
        """Last ``count`` CLOSED bars (forming bar dropped), oldest → newest."""
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count + 1)
        if rates is None or len(rates) < 2:
            return []
        out: list[Candle] = []
        for r in rates[:-1]:
            vol = float(r["real_volume"]) if r["real_volume"] > 0 else float(r["tick_volume"])
            out.append(
                Candle(self._to_utc(int(r["time"])), float(r["open"]), float(r["high"]),
                       float(r["low"]), float(r["close"]), vol)
            )
        return out

    # ── account / governor reads ──────────────────────────────────────
    def _position(self):
        for p in mt5.positions_get(symbol=self.cfg.symbol) or []:
            if p.magic == self.cfg.magic:
                return p
        return None

    def _consec_losses(self) -> int:
        now = datetime.now(timezone.utc) + timedelta(hours=self.cfg.server_utc_offset_h + 2)
        deals = mt5.history_deals_get(now - timedelta(days=45), now) or []
        open_pid = getattr(self._position(), "ticket", None)
        bypos: dict[int, list] = {}
        for d in deals:
            if d.magic == self.cfg.magic:
                bypos.setdefault(d.position_id, []).append(d)
        closed: list[tuple[int, float]] = []
        for pid, ds in bypos.items():
            if pid == open_pid or not any(d.entry == mt5.DEAL_ENTRY_OUT for d in ds):
                continue
            net = sum(d.profit + d.commission + d.swap for d in ds)
            closed.append((max(d.time for d in ds), net))
        closed.sort()
        n = 0
        for _, net in reversed(closed):
            if net < 0:
                n += 1
            else:
                break
        return n

    def _roll_day(self, equity: float) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.get("day_anchor") != today:
            self.state["day_anchor"] = today
            self.state["day_start_equity"] = equity
            self.state["trades_today"] = 0
            self._save_state()
            self.log.info("UTC day rollover — day_start_equity=%.2f", equity)

    def _snapshot(self, bars: list[Candle]) -> Ctx:
        acc = mt5.account_info()
        equity = acc.equity if acc else self.state.get("peak_equity", 0.0)
        self.state["peak_equity"] = max(self.state.get("peak_equity", equity), equity)
        self._roll_day(equity)
        init = self.state.get("initial_equity", equity) or equity
        peak = self.state.get("peak_equity", equity) or equity
        day0 = self.state.get("day_start_equity", equity) or equity
        pos = self._position()
        ps = self.state.get("pos") or {}
        bars_held = 0
        bars_since_scale = -1
        if pos is not None and ps:
            # A bar counts once it CLOSES after the event (backtest enters at the
            # signal bar's close, so the next closed bar is bars_held == 1).
            tf = self._tf_seconds()
            entry_ts = ps.get("entry_ts", 0)
            bars_held = sum(1 for b in bars if b.time.timestamp() + tf > entry_ts)
            if ps.get("scaled"):
                sts = ps.get("scale_ts", 0)
                bars_since_scale = sum(1 for b in bars if b.time.timestamp() + tf > sts)
        return Ctx(
            bars=bars,
            position=1 if pos is not None else 0,
            bars_held=bars_held,
            bars_since_scale=bars_since_scale,
            equity=equity,
            day_pnl_pct=100.0 * (equity - day0) / day0 if day0 else 0.0,
            trades_today=int(self.state.get("trades_today", 0)),
            consec_losses=self._consec_losses(),
            dd_from_peak_pct=100.0 * (peak - equity) / peak if peak else 0.0,
            total_pnl_pct=100.0 * (equity - init) / init if init else 0.0,
            hour_utc=bars[-1].time.hour if bars else 0,
        )

    # ── order plumbing (the ONLY place orders are touched) ────────────
    def _round_price(self, px: float) -> float:
        info = mt5.symbol_info(self.cfg.symbol)
        return round(px, info.digits) if info else px

    def _round_lots(self, lots: float) -> float:
        info = mt5.symbol_info(self.cfg.symbol)
        step = info.volume_step or 0.01
        lots = math.floor(lots / step + 1e-9) * step
        return round(lots, 8)

    def _lots_for_risk(self, risk_pct: float, stop_dist: float, equity: float) -> float:
        info = mt5.symbol_info(self.cfg.symbol)
        if info is None or stop_dist <= 0:
            return 0.0
        tick_size = info.trade_tick_size or info.point
        tick_value = info.trade_tick_value
        if not tick_size or not tick_value:
            return 0.0
        loss_per_lot = stop_dist / tick_size * tick_value
        if loss_per_lot <= 0:
            return 0.0
        lots = self._round_lots((equity * risk_pct / 100.0) / loss_per_lot)
        if lots < info.volume_min:
            return 0.0
        return min(lots, info.volume_max)

    def _send(self, request: dict):
        """order_send with filling-mode fallback (IOC → FOK → RETURN)."""
        for filling in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
            request["type_filling"] = filling
            res = mt5.order_send(request)
            if res is None:
                self.log.error("order_send returned None: %s", mt5.last_error())
                return None
            if res.retcode == mt5.TRADE_RETCODE_DONE:
                return res
            if res.retcode != mt5.TRADE_RETCODE_INVALID_FILL:
                self.log.error("order_send rejected: retcode=%s comment=%s", res.retcode, res.comment)
                return res
        return res

    def open_long(self, dec: Decision) -> bool:
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        acc = mt5.account_info()
        if tick is None or acc is None:
            return False
        lots = self._lots_for_risk(dec.risk_pct, dec.stop_dist, acc.equity)
        if lots <= 0:
            self.log.warning("entry skipped — computed lots below broker minimum "
                             "(risk %.2f%%, stop %.2f)", dec.risk_pct, dec.stop_dist)
            return False
        sl = self._round_price(tick.ask - dec.stop_dist)
        tp = self._round_price(tick.ask + dec.target_rr * dec.stop_dist) if dec.target_rr > 0 else 0.0
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.cfg.symbol,
            "volume": lots,
            "type": mt5.ORDER_TYPE_BUY,
            "price": tick.ask,
            "sl": sl,
            "tp": tp,
            "deviation": self.cfg.deviation_points,
            "magic": self.cfg.magic,
            "comment": self.cfg.name[:24],
            "type_time": mt5.ORDER_TIME_GTC,
        }
        res = self._send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            return False
        self.state["pos"] = {
            "ticket": res.order,
            "entry": res.price or tick.ask,
            "entry_ts": datetime.now(timezone.utc).timestamp(),
            "scaled": False,
            "scale_ts": 0,
            "scale_at": dec.scale_at,
            "scale_frac": dec.scale_frac,
            "scale_be": bool(dec.scale_be),
            "trail_dist": dec.trail_dist,
        }
        self.state["trades_today"] = int(self.state.get("trades_today", 0)) + 1
        self._save_state()
        self.log.info("LONG %s %.2f lots @ %.2f sl=%.2f tp=%.2f risk=%.2f%% [%s]",
                      self.cfg.symbol, lots, res.price or tick.ask, sl, tp,
                      dec.risk_pct, dec.reason or "entry")
        return True

    def close_long(self, frac: float = 1.0, reason: str = "") -> bool:
        pos = self._position()
        if pos is None:
            return False
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        vol = self._round_lots(pos.volume * frac)
        info = mt5.symbol_info(self.cfg.symbol)
        if vol < (info.volume_min if info else 0.01):
            vol = pos.volume
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.cfg.symbol,
            "volume": vol,
            "type": mt5.ORDER_TYPE_SELL,
            "position": pos.ticket,
            "price": tick.bid if tick else 0.0,
            "deviation": self.cfg.deviation_points,
            "magic": self.cfg.magic,
            "comment": (reason or "exit")[:24],
        }
        res = self._send(req)
        ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
        if ok:
            self.log.info("CLOSE %.0f%% of %s @ %.2f [%s]",
                          frac * 100, self.cfg.symbol, res.price or 0.0, reason)
            if frac >= 0.999:
                self.state["pos"] = None
                self._save_state()
        return ok

    def modify_sl(self, new_sl: float) -> bool:
        pos = self._position()
        if pos is None:
            return False
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": self.cfg.symbol,
            "position": pos.ticket,
            "sl": self._round_price(new_sl),
            "tp": pos.tp,
        }
        res = mt5.order_send(req)
        return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE

    # ── intra-bar management: scale stage + break-even + trail ────────
    def _manage_intrabar(self) -> None:
        ps = self.state.get("pos")
        pos = self._position()
        if pos is None:
            if ps:
                self.log.info("position closed by broker (SL/TP hit or manual)")
                self.state["pos"] = None
                self._save_state()
            return
        if not ps:
            # restart with an unknown open position — adopt it conservatively
            self.state["pos"] = {
                "ticket": pos.ticket, "entry": pos.price_open,
                "entry_ts": datetime.now(timezone.utc).timestamp(),
                "scaled": False, "scale_ts": 0, "scale_at": 0.0,
                "scale_frac": 0.0, "scale_be": False, "trail_dist": 0.0,
            }
            self._save_state()
            return
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if tick is None:
            return
        # one-time partial bank at the scale level (POC), then BE + arm trail
        if ps.get("scale_at") and ps.get("scale_frac") and not ps.get("scaled"):
            if tick.bid >= ps["scale_at"]:
                if self.close_long(ps["scale_frac"], reason="scale@POC"):
                    ps["scaled"] = True
                    ps["scale_ts"] = datetime.now(timezone.utc).timestamp()
                    if ps.get("scale_be"):
                        be = max(ps["entry"], pos.sl or 0.0)
                        if self.modify_sl(be):
                            self.log.info("stop moved to break-even %.2f", be)
                    self.state["pos"] = ps
                    self._save_state()
        # trail the runner once scaled
        if ps.get("scaled") and ps.get("trail_dist", 0) > 0:
            desired = tick.bid - ps["trail_dist"]
            info = mt5.symbol_info(self.cfg.symbol)
            min_step = (info.trade_tick_size or info.point) if info else 0.01
            cur_sl = pos.sl or 0.0
            if desired > cur_sl + min_step:
                if self.modify_sl(desired):
                    self.log.info("trail: sl → %.2f", desired)

    # ── FTMO inactivity watchdog (account keep-alive) ─────────────────
    def _watchdog_check(self) -> None:
        """FTMO closes accounts after 30 idle days. If ``watchdog_days`` pass
        with no NEW deal on the WHOLE account (any magic, manual included),
        place a minimum-lot nudge and close it seconds later.

        Orthogonal to the alpha path by construction: separate magic
        (``cfg.magic + 99``) so governor metrics (consec_losses, trades_today)
        never see it; throttled to one check per hour; self-resetting because
        the nudge itself lands in deal history.
        """
        if self.cfg.watchdog_days <= 0:
            return
        now = datetime.now(timezone.utc)
        if now.timestamp() - self.state.get("wd_last_check", 0) < 3600:
            return
        self.state["wd_last_check"] = now.timestamp()
        self._save_state()
        self._close_nudges()           # finish any round-trip a failed close left open
        server_now = now + timedelta(hours=self.cfg.server_utc_offset_h + 2)
        deals = mt5.history_deals_get(
            server_now - timedelta(days=self.cfg.watchdog_days + 25), server_now) or []
        last_in = 0
        for d in deals:
            if d.entry == mt5.DEAL_ENTRY_IN:
                last_in = max(last_in, d.time)
        if mt5.positions_get():        # an open position = account is active
            return
        server_epoch = now.timestamp() + self.cfg.server_utc_offset_h * 3600
        idle_days = (server_epoch - last_in) / 86400.0 if last_in else float("inf")
        if idle_days < self.cfg.watchdog_days:
            return
        self.log.warning("WATCHDOG: %.1f days without any account trade — "
                         "placing keep-alive nudge on %s",
                         min(idle_days, 99.0), self.cfg.symbol)
        self._nudge()

    def _nudge(self) -> None:
        """Minimum-lot market round-trip with its own magic; cost ≈ one spread."""
        info = mt5.symbol_info(self.cfg.symbol)
        tick = mt5.symbol_info_tick(self.cfg.symbol)
        if info is None or tick is None or tick.ask <= 0:
            self.log.warning("watchdog: no quote — market closed? retrying next hour")
            return
        magic = self.cfg.magic + 99
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.cfg.symbol,
            "volume": info.volume_min,
            "type": mt5.ORDER_TYPE_BUY,
            "price": tick.ask,
            "sl": self._round_price(tick.ask * 0.98),   # hard stop rides in-order
            "deviation": self.cfg.deviation_points,
            "magic": magic,
            "comment": "keepalive-nudge",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        res = self._send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            self.log.warning("watchdog: nudge open rejected — retrying next hour")
            return
        _time.sleep(5)
        self._close_nudges()

    def _close_nudges(self) -> None:
        """Close every position carrying the keep-alive magic (cfg.magic + 99)."""
        magic = self.cfg.magic + 99
        for p in mt5.positions_get(symbol=self.cfg.symbol) or []:
            if p.magic != magic:
                continue
            tick = mt5.symbol_info_tick(self.cfg.symbol)
            close = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": self.cfg.symbol,
                "volume": p.volume,
                "type": mt5.ORDER_TYPE_SELL,
                "position": p.ticket,
                "price": tick.bid if tick else 0.0,
                "deviation": self.cfg.deviation_points,
                "magic": magic,
                "comment": "keepalive-close",
            }
            r2 = self._send(close)
            if r2 is not None and r2.retcode == mt5.TRADE_RETCODE_DONE:
                self.log.info("WATCHDOG: keep-alive round-trip done (%.2f lots %s)",
                              p.volume, self.cfg.symbol)
            else:
                self.log.error("watchdog: nudge CLOSE failed — position %s keeps its "
                               "2%% hard stop; retry next hour", p.ticket)

    # ── main loop ─────────────────────────────────────────────────────
    def run(self, on_bar: Callable[[Ctx], Decision]) -> None:
        """Poll loop: strategy decisions at bar close; scale/trail intra-bar."""
        self.connect()
        self.log.info("engine loop started (tf=%ss poll=%ss warmup=%s)",
                      self._tf_seconds(), self.cfg.poll_seconds, self.cfg.warmup_bars)
        while True:
            try:
                bars = self.closed_bars(self.cfg.symbol, self.cfg.timeframe, self.cfg.warmup_bars)
                if bars:
                    t = int(bars[-1].time.timestamp())
                    if t > self._last_closed_bar:
                        self._last_closed_bar = t
                        ctx = self._snapshot(bars)
                        dec = on_bar(ctx)
                        self._apply(dec, ctx)
                self._manage_intrabar()
                self._watchdog_check()
            except KeyboardInterrupt:
                self.log.info("interrupted — leaving positions (hard stops ride in-order)")
                break
            except Exception as exc:  # never crash the trading loop
                self.log.exception("loop error (continuing): %s", exc)
            _time.sleep(self.cfg.poll_seconds)
        mt5.shutdown()

    def _apply(self, dec: Decision, ctx: Ctx) -> None:
        if dec.signal == "FLAT" and ctx.position == 1:
            self.close_long(1.0, reason=dec.reason or "flat")
        elif dec.signal == "BUY" and ctx.position == 0:
            self.open_long(dec)
        elif dec.signal not in ("HOLD", "BUY", "FLAT"):
            self.log.warning("unknown signal %r ignored", dec.signal)
