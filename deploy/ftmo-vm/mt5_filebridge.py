"""mt5_filebridge — drop-in replacement for the MetaTrader5 python package,
speaking a file protocol to the ApexBridge.mq5 EA inside the terminal.

Why: the MetaTrader5 package's shared-memory IPC never completes under Wine on
the Oracle VM (falsified across wine 9/11 stable+staging, two package versions,
every attach mode — see project memory). The terminal itself runs fine, so the
EA executes orders natively and exchanges flat key=value/CSV files with this
module through the MQL5 sandbox (``MQL5/Files/apex``). Runs on NATIVE Linux
Python — no Wine Python anywhere.

API surface mirrors the subset of the MetaTrader5 module used by apex_mt5.py:
initialize/shutdown/last_error, account_info, symbol_select/info/info_tick,
copy_rates_from_pos, positions_get, history_deals_get, order_send + constants.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

# ── constants (values match the real MetaTrader5 module) ──────────────────
TIMEFRAME_M15 = "M15"
TIMEFRAME_H1 = "H1"
TIMEFRAME_H4 = "H4"
TIMEFRAME_D1 = "D1"
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
TRADE_ACTION_DEAL = 1
TRADE_ACTION_SLTP = 6
ORDER_TIME_GTC = 0
ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_INVALID_FILL = 10030
DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1

BRIDGE_DIR = Path(os.environ.get(
    "APEX_BRIDGE_DIR",
    os.path.expanduser(
        "~/.mt5/drive_c/Program Files/MetaTrader 5/MQL5/Files/apex"),
))
FRESH_S = 15.0          # snapshot files older than this = terminal/EA down
CMD_TIMEOUT_S = 25.0

_last_error: tuple[int, str] = (0, "ok")
_cmd_seq = 0


def _set_err(code: int, msg: str) -> None:
    global _last_error
    _last_error = (code, msg)


def last_error() -> tuple[int, str]:
    return _last_error


# ── file helpers ───────────────────────────────────────────────────────────
def _read_kv(name: str) -> Optional[dict[str, str]]:
    """Read a key=value snapshot; None if missing or stale."""
    p = BRIDGE_DIR / name
    try:
        if time.time() - p.stat().st_mtime > FRESH_S:
            return None
        out: dict[str, str] = {}
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
        return out or None
    except OSError:
        return None


def _f(d: dict[str, str], k: str, default: float = 0.0) -> float:
    try:
        return float(d.get(k, default))
    except ValueError:
        return default


# ── lifecycle ──────────────────────────────────────────────────────────────
def initialize(*_path: Any, **kwargs: Any) -> bool:
    """Wait for a fresh, connected EA heartbeat. Login args are ignored —
    the terminal logs itself in via the generated start .ini."""
    timeout_s = float(kwargs.get("timeout", 120_000)) / 1000.0
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        hb = _read_kv("heartbeat.txt")
        if hb is not None and hb.get("connected") == "1":
            _set_err(0, "ok")
            return True
        time.sleep(2.0)
    _set_err(-10005, "bridge heartbeat stale or terminal disconnected "
                     f"(dir={BRIDGE_DIR})")
    return False


def shutdown() -> None:
    """Nothing to tear down — the EA owns the terminal side."""


def symbol_select(_symbol: str, _enable: bool = True) -> bool:
    return True


# ── account / symbol snapshots ─────────────────────────────────────────────
def account_info() -> Optional[SimpleNamespace]:
    hb = _read_kv("heartbeat.txt")
    if hb is None:
        return None
    return SimpleNamespace(
        login=int(_f(hb, "login")), server=hb.get("server", ""),
        currency=hb.get("currency", "USD"),
        balance=_f(hb, "balance"), equity=_f(hb, "equity"),
    )


def terminal_info() -> Optional[SimpleNamespace]:
    hb = _read_kv("heartbeat.txt")
    if hb is None:
        return None
    return SimpleNamespace(connected=hb.get("connected") == "1",
                           name="ApexBridge", build=0)


def symbol_info(symbol: str) -> Optional[SimpleNamespace]:
    d = _read_kv(f"sym_{symbol}.txt")
    if d is None:
        return None
    return SimpleNamespace(
        digits=int(_f(d, "digits", 2)), point=_f(d, "point", 0.01),
        trade_tick_size=_f(d, "tick_size", 0.01),
        trade_tick_value=_f(d, "tick_value", 0.0),
        volume_min=_f(d, "vol_min", 0.01), volume_max=_f(d, "vol_max", 100.0),
        volume_step=_f(d, "vol_step", 0.01), filling_mode=2,
    )


def symbol_info_tick(symbol: str) -> Optional[SimpleNamespace]:
    d = _read_kv(f"sym_{symbol}.txt")
    if d is None:
        return None
    return SimpleNamespace(bid=_f(d, "bid"), ask=_f(d, "ask"),
                           time=int(_f(d, "ts")))


# ── market data ────────────────────────────────────────────────────────────
def copy_rates_from_pos(symbol: str, timeframe: str, start: int,
                        count: int) -> Optional[list[dict[str, float]]]:
    """Rows oldest→newest incl. the forming bar (same as the real API)."""
    p = BRIDGE_DIR / f"bars_{symbol}_{timeframe}.csv"
    try:
        if time.time() - p.stat().st_mtime > 600.0:   # bars refresh per-bar
            _set_err(-2, f"bars file stale: {p.name}")
            return None
        rows: list[dict[str, float]] = []
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.strip().split(",")
            if len(parts) < 7:
                continue
            try:
                rows.append({
                    "time": int(parts[0]), "open": float(parts[1]),
                    "high": float(parts[2]), "low": float(parts[3]),
                    "close": float(parts[4]), "tick_volume": float(parts[5]),
                    "real_volume": float(parts[6]),
                })
            except ValueError:
                continue
        if not rows:
            return None
        end = len(rows) - start
        return rows[max(0, end - count):end] if end > 0 else None
    except OSError:
        _set_err(-2, f"bars file missing: {p.name}")
        return None


# ── positions / history ────────────────────────────────────────────────────
def positions_get(symbol: Optional[str] = None, **_kw: Any) -> list[SimpleNamespace]:
    p = BRIDGE_DIR / "positions.txt"
    out: list[SimpleNamespace] = []
    try:
        if time.time() - p.stat().st_mtime > FRESH_S:
            return out
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            f = line.strip().split(";")
            if len(f) < 8:
                continue
            try:
                pos = SimpleNamespace(
                    ticket=int(f[0]), magic=int(f[1]), symbol=f[2],
                    volume=float(f[3]), price_open=float(f[4]),
                    sl=float(f[5]), tp=float(f[6]), type=int(f[7]),
                )
            except ValueError:
                continue
            if symbol is None or pos.symbol == symbol:
                out.append(pos)
    except OSError:
        pass
    return out


def history_deals_get(dfrom: datetime, dto: datetime, **_kw: Any) -> list[SimpleNamespace]:
    p = BRIDGE_DIR / "deals.txt"
    out: list[SimpleNamespace] = []
    try:
        lo, hi = dfrom.timestamp(), dto.timestamp()
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            f = line.strip().split(";")
            if len(f) < 8:
                continue
            try:
                t = int(f[3])
                if not (lo <= t <= hi):
                    continue
                out.append(SimpleNamespace(
                    position_id=int(f[0]), magic=int(f[1]), entry=int(f[2]),
                    time=t, profit=float(f[4]), commission=float(f[5]),
                    swap=float(f[6]), symbol=f[7],
                ))
            except ValueError:
                continue
    except OSError:
        pass
    return out


# ── order execution via command files ──────────────────────────────────────
def _write_cmd(fields: dict[str, Any]) -> str:
    global _cmd_seq
    _cmd_seq += 1
    cid = f"{int(time.time() * 1000)}_{os.getpid()}_{_cmd_seq}"
    fields["id"] = cid
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    body = "".join(f"{k}={v}\n" for k, v in fields.items())
    tmp = BRIDGE_DIR / f"cmd_{cid}.txt.tmp"
    tmp.write_text(body, encoding="utf-8")
    tmp.rename(BRIDGE_DIR / f"cmd_{cid}.txt")
    return cid


def _wait_res(cid: str) -> Optional[SimpleNamespace]:
    p = BRIDGE_DIR / f"res_{cid}.txt"
    deadline = time.time() + CMD_TIMEOUT_S
    while time.time() < deadline:
        if p.exists():
            time.sleep(0.1)            # let the EA finish the write+move
            d: dict[str, str] = {}
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" in line:
                    k, _, v = line.partition("=")
                    d[k.strip()] = v.strip()
            try:
                p.unlink()
            except OSError:
                pass
            return SimpleNamespace(
                retcode=int(_f(d, "retcode")), price=_f(d, "price"),
                order=int(_f(d, "order")), comment=d.get("error", ""),
            )
        time.sleep(0.25)
    _set_err(-10008, f"bridge command timeout ({cid})")
    return None


def order_send(request: dict[str, Any]) -> Optional[SimpleNamespace]:
    """Translate a MetaTrader5-style request dict into a bridge command."""
    action = request.get("action")
    if action == TRADE_ACTION_SLTP:
        cid = _write_cmd({
            "action": "MODIFY_SL",
            "position": int(request.get("position", 0)),
            "sl": float(request.get("sl", 0.0)),
            "tp": float(request.get("tp", 0.0) or 0.0),
        })
    elif action == TRADE_ACTION_DEAL and "position" in request:
        cid = _write_cmd({
            "action": "CLOSE",
            "position": int(request["position"]),
            "volume": float(request.get("volume", 0.0)),
            "deviation": int(request.get("deviation", 50)),
            "comment": str(request.get("comment", ""))[:24],
        })
    elif action == TRADE_ACTION_DEAL:
        cid = _write_cmd({
            "action": "OPEN_BUY",
            "symbol": request["symbol"],
            "volume": float(request["volume"]),
            "sl": float(request.get("sl", 0.0)),
            "tp": float(request.get("tp", 0.0) or 0.0),
            "deviation": int(request.get("deviation", 50)),
            "magic": int(request.get("magic", 0)),
            "comment": str(request.get("comment", ""))[:24],
        })
    else:
        _set_err(-3, f"unsupported request action {action!r}")
        return None
    return _wait_res(cid)
