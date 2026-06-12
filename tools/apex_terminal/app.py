"""Apex Command Terminal â€” local management backend for the V4 Institutional VM.

Architecture: ZERO remote footprint. The Oracle VM runs no web servers; every
panel on the dashboard is fed by single-shot SSH commands (or a streamed
``tail -F`` for the live log terminals) using the existing deploy key. The
backend binds to 127.0.0.1 only â€” credentials never leave the machine except
over SSH to the VM itself.

Run via ``start.bat`` (installs deps, boots uvicorn, opens the browser).
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

log = logging.getLogger("apex_terminal")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")

ROOT = Path(__file__).resolve().parent.parent          # C:\workspace\Oracle\Algo-VM
STATIC = Path(__file__).resolve().parent / "static"
KEY_FILE = ROOT / "ssh-key-2026-06-10.key"
REMOTE_DIR = "~/apex-v4"

LOG_FILES = {
    "btc": "global_macro_v4.log",
    "us500": "auction_flow_v5_1.log",
}
STATE_FILES = {
    "btc": "global_macro_v4_state.json",
    "us500": "auction_flow_v5_1_state.json",
}
ENV_KEYS = [
    "MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER", "MT5_PATH",
    "BTC_SYMBOL", "US500_SYMBOL", "SERVER_UTC_OFFSET_HOURS",
    "CHALLENGE_MODE", "MAGIC_BTC", "MAGIC_US500", "POLL_SECONDS",
]

_ssh_gate = asyncio.Semaphore(4)   # don't stampede a 1GB VM


def _load_host() -> str:
    """Resolve ``user@ip`` from server_info.txt, with a pinned fallback."""
    user, ip = "ubuntu", "<VM-IP>"
    info = ROOT / "server_info.txt"
    if info.exists():
        text = info.read_text(encoding="utf-8-sig")
        m = re.search(r"IP Address:\s*([\d.]+)", text)
        if m:
            ip = m.group(1)
        m = re.search(r"Username:\s*(\S+)", text)
        if m:
            user = m.group(1)
    return f"{user}@{ip}"


HOST = _load_host()
SSH_BASE = [
    "ssh", "-i", str(KEY_FILE),
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8",
    "-o", "StrictHostKeyChecking=accept-new",
    HOST,
]


async def ssh_run(command: str, timeout: float = 25.0,
                  stdin_data: Optional[str] = None) -> tuple[int, str, str]:
    """Run one remote command; returns (rc, stdout, stderr).

    The command travels as a SINGLE argv element so local shells never touch
    its quoting (hard-won lesson: Windows quoting mangles inline pipes/quotes).
    """
    async with _ssh_gate:
        proc = await asyncio.create_subprocess_exec(
            *SSH_BASE, command,
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(stdin_data.encode() if stdin_data is not None else None),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            return 124, "", f"ssh timeout after {timeout}s"
        return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


app = FastAPI(title="Apex Command Terminal")


@app.get("/")
async def index() -> FileResponse:
    """Serve the single-page dashboard."""
    return FileResponse(STATIC / "index.html")


@app.get("/favicon.svg")
@app.get("/favicon.ico")
async def favicon() -> FileResponse:
    """Geometric neon terminal mark for the browser tab."""
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")


# â”€â”€ system health & topology â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
HEALTH_CMD = r"""
head -1 /proc/stat; sleep 1; head -1 /proc/stat
echo '###MEM'; free -m
echo '###LOAD'; cat /proc/loadavg; uptime -p
echo '###TOPO'
echo PREFIX=$([ -d $HOME/.mt5/drive_c ] && echo 1 || echo 0)
echo MT5=$(pgrep -fc 'terminal64[.]exe' || true)
echo XVFB=$(pgrep -fc '[X]vfb' || true)
echo BTC=$(pgrep -fc 'global_macro_v4[.]py' || true)
echo US500=$(pgrep -fc 'auction_flow_v5_1_hybrid[.]py' || true)
echo '###TMUX'
tmux list-windows -t apex -F '#{window_name}|#{pane_dead}' 2>/dev/null || echo NO_SESSION
echo '###SESS'
tmux display-message -p -t apex '#{session_created}' 2>/dev/null || echo 0
""".strip()


def _cpu_pct(line1: str, line2: str) -> float:
    """% busy between two /proc/stat 'cpu' samples."""
    try:
        a = [int(x) for x in line1.split()[1:]]
        b = [int(x) for x in line2.split()[1:]]
        idle = (b[3] + b[4]) - (a[3] + a[4])      # idle + iowait
        total = sum(b) - sum(a)
        return round(100.0 * (total - idle) / total, 1) if total > 0 else 0.0
    except (ValueError, IndexError):
        return 0.0


@app.get("/api/health")
async def health() -> JSONResponse:
    """One SSH round-trip: CPU/RAM/swap + process topology + tmux state."""
    rc, out, err = await ssh_run(HEALTH_CMD, timeout=20)
    if rc != 0:
        return JSONResponse({"ok": False, "error": err.strip() or f"ssh rc={rc}"})
    sections: dict[str, list[str]] = {"HEAD": []}
    cur = "HEAD"
    for line in out.splitlines():
        if line.startswith("###"):
            cur = line[3:]
            sections[cur] = []
        elif line.strip():
            sections[cur].append(line)

    head = sections.get("HEAD", [])
    cpu = _cpu_pct(head[0], head[1]) if len(head) >= 2 else 0.0

    mem = {"total": 0, "used": 0}
    swap = {"total": 0, "used": 0}
    for line in sections.get("MEM", []):
        parts = line.split()
        if line.startswith("Mem:"):
            mem = {"total": int(parts[1]), "used": int(parts[2])}
        elif line.startswith("Swap:"):
            swap = {"total": int(parts[1]), "used": int(parts[2])}

    load_lines = sections.get("LOAD", [""])
    load1 = load_lines[0].split()[0] if load_lines and load_lines[0] else "0"
    uptime = load_lines[1] if len(load_lines) > 1 else ""

    topo: dict[str, int] = {}
    for line in sections.get("TOPO", []):
        if "=" in line:
            k, _, v = line.partition("=")
            try:
                topo[k.strip()] = int(v.strip() or 0)
            except ValueError:
                topo[k.strip()] = 0

    tmux_raw = sections.get("TMUX", ["NO_SESSION"])
    tmux = {"session": tmux_raw != ["NO_SESSION"], "windows": [], "created": 0}
    if tmux["session"]:
        for line in tmux_raw:
            name, _, dead = line.partition("|")
            tmux["windows"].append({"name": name, "dead": dead.strip() == "1"})
    sess = sections.get("SESS", ["0"])
    try:
        tmux["created"] = int(sess[0].strip())
    except (ValueError, IndexError):
        tmux["created"] = 0

    return JSONResponse({
        "ok": True, "cpu": cpu, "mem": mem, "swap": swap,
        "load1": load1, "uptime": uptime, "topology": topo, "tmux": tmux,
    })


# â”€â”€ FTMO guardrails â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
GUARD_CMD = (
    f"echo '###BTC_STATE'; cat {REMOTE_DIR}/{STATE_FILES['btc']} 2>/dev/null || echo {{}};"
    f"echo '###US_STATE'; cat {REMOTE_DIR}/{STATE_FILES['us500']} 2>/dev/null || echo {{}};"
    f"echo '###BTC_LOG'; grep -F 'bar ' {REMOTE_DIR}/{LOG_FILES['btc']} 2>/dev/null | tail -1;"
    f"echo '###US_LOG'; grep -F 'bar ' {REMOTE_DIR}/{LOG_FILES['us500']} 2>/dev/null | tail -1;"
    f"echo '###MODE'; grep -i '^CHALLENGE_MODE' {REMOTE_DIR}/.env 2>/dev/null || echo CHALLENGE_MODE=unset"
)

_METRIC_RE = re.compile(r"\b([a-z_0-9]+)=(-?\d+(?:\.\d+)?)\b")


@app.get("/api/guardrails")
async def guardrails() -> JSONResponse:
    """State JSONs + last logged bar metrics per leg, one SSH round-trip."""
    import json as _json
    rc, out, err = await ssh_run(GUARD_CMD, timeout=20)
    if rc != 0:
        return JSONResponse({"ok": False, "error": err.strip() or f"ssh rc={rc}"})
    sections: dict[str, list[str]] = {}
    cur = ""
    for line in out.splitlines():
        if line.startswith("###"):
            cur = line[3:]
            sections[cur] = []
        elif cur:
            sections[cur].append(line)

    def _state(key: str) -> dict:
        try:
            return _json.loads("\n".join(sections.get(key, ["{}"])) or "{}")
        except _json.JSONDecodeError:
            return {}

    def _bar(key: str) -> dict[str, float]:
        text = " ".join(sections.get(key, []))
        return {k: float(v) for k, v in _METRIC_RE.findall(text)}

    mode_line = " ".join(sections.get("MODE", []))
    challenge = "true" in mode_line.lower()

    return JSONResponse({
        "ok": True,
        "challenge_mode": challenge,
        "btc": {"state": _state("BTC_STATE"), "bar": _bar("BTC_LOG")},
        "us500": {"state": _state("US_STATE"), "bar": _bar("US_LOG")},
    })


# â”€â”€ stack control â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
STOP_CMD = (
    "tmux kill-session -t apex 2>/dev/null; "
    "WINEPREFIX=$HOME/.mt5 wineserver -k 2>/dev/null; "
    "pkill -f '[X]vfb :1' 2>/dev/null; echo STOPPED"
)
START_CMD = (
    f"test -f {REMOTE_DIR}/.env || {{ echo NO_ENV; exit 0; }}; "
    f"nohup bash {REMOTE_DIR}/remote/launch_all.sh > ~/launch_ui.log 2>&1 & echo STARTING"
)
LEG_CMDS = {
    "btc": ("btc", "global_macro_v4.py", "btc_console.log"),
    "us500": ("us500", "auction_flow_v5_1_hybrid.py", "us500_console.log"),
}


class ControlReq(BaseModel):
    action: str


@app.post("/api/control")
async def control(req: ControlReq) -> JSONResponse:
    """start | stop | restart | restart_btc | restart_us500."""
    action = req.action
    if action == "stop":
        cmd = STOP_CMD
    elif action == "start":
        cmd = START_CMD
    elif action == "restart":
        cmd = f"{STOP_CMD}; sleep 2; {START_CMD}"
    elif action in ("restart_btc", "restart_us500"):
        win, _script, _console = LEG_CMDS[action.removeprefix("restart_")]
        cmd = (f"tmux kill-window -t apex:{win} 2>/dev/null; "
               f"tmux new-window -t apex -n {win} "
               f"'bash $HOME/apex-v4/remote/run_leg.sh {win}' "
               f"&& echo LEG_RESTARTED || echo NO_SESSION")
    else:
        return JSONResponse({"ok": False, "error": f"unknown action {action!r}"}, status_code=400)

    rc, out, err = await ssh_run(cmd, timeout=30)
    result = out.strip().splitlines()[-1] if out.strip() else ""
    ok = rc == 0 and result not in ("NO_ENV", "NO_SESSION")
    log.info("control %s â†’ rc=%s result=%s", action, rc, result)
    return JSONResponse({"ok": ok, "result": result or err.strip(), "action": action})


# â”€â”€ remote .env editor â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.get("/api/env")
async def env_get() -> JSONResponse:
    """Read the remote .env (falls back to the template for first-run)."""
    rc, out, err = await ssh_run(
        f"cat {REMOTE_DIR}/.env 2>/dev/null && echo '###SRC=env' "
        f"|| {{ cat {REMOTE_DIR}/.env.template 2>/dev/null; echo '###SRC=template'; }}",
        timeout=15,
    )
    if rc != 0:
        return JSONResponse({"ok": False, "error": err.strip() or f"ssh rc={rc}"})
    values: dict[str, str] = {}
    source = "template"
    for line in out.splitlines():
        if line.startswith("###SRC="):
            source = line.split("=", 1)[1]
            continue
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        values[k.strip()] = v.strip()
    return JSONResponse({"ok": True, "source": source,
                         "values": {k: values.get(k, "") for k in ENV_KEYS}})


class EnvReq(BaseModel):
    values: dict[str, str]


@app.post("/api/env")
async def env_save(req: EnvReq) -> JSONResponse:
    """Write the merged .env back to the VM (piped via stdin, chmod 600)."""
    merged = {k: str(req.values.get(k, "")).strip() for k in ENV_KEYS}
    if not merged["MT5_LOGIN"] or not merged["MT5_PASSWORD"]:
        return JSONResponse({"ok": False, "error": "MT5_LOGIN and MT5_PASSWORD are required"},
                            status_code=400)
    content = "# Apex V4 Institutional â€” written by Apex Command Terminal\n"
    content += "\n".join(f"{k}={merged[k]}" for k in ENV_KEYS) + "\n"
    rc, out, err = await ssh_run(
        f"cat > {REMOTE_DIR}/.env && chmod 600 {REMOTE_DIR}/.env && echo SAVED",
        timeout=15, stdin_data=content,
    )
    ok = rc == 0 and "SAVED" in out
    log.info("env save â†’ %s", "SAVED" if ok else err.strip())
    return JSONResponse({"ok": ok, "error": "" if ok else err.strip()})


# â”€â”€ live log streaming over WebSocket â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.websocket("/ws/logs/{leg}")
async def ws_logs(ws: WebSocket, leg: str) -> None:
    """Stream ``tail -F`` of a remote strategy log into the browser."""
    fname = LOG_FILES.get(leg)
    await ws.accept()
    if fname is None:
        await ws.send_text(f"!! unknown log channel {leg!r}")
        await ws.close()
        return
    proc = await asyncio.create_subprocess_exec(
        *SSH_BASE, f"tail -n 200 -F {REMOTE_DIR}/{fname} 2>/dev/null",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    log.info("log stream open: %s", leg)
    try:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                await ws.send_text("!! stream ended (ssh closed) â€” reconnectingâ€¦")
                break
            await ws.send_text(line.decode(errors="replace").rstrip("\r\n"))
    except (WebSocketDisconnect, ConnectionResetError, RuntimeError):
        pass
    finally:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        log.info("log stream closed: %s", leg)

