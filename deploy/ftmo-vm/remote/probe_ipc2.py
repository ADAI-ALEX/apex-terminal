"""IPC probe v2: bare attach (no path) vs path attach, against a pre-running
terminal on a freshly-verified display. Run inside Wine Python."""
import time

import MetaTrader5 as mt5

PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

for label, kwargs in (("bare-attach", {}), ("path-attach", {"path": PATH})):
    t0 = time.time()
    if "path" in kwargs:
        ok = mt5.initialize(kwargs["path"], timeout=120_000)
    else:
        ok = mt5.initialize(timeout=120_000)
    dt = time.time() - t0
    print(f"{label} -> INIT={ok} err={mt5.last_error()} ({dt:.0f}s)", flush=True)
    if ok:
        ti = mt5.terminal_info()
        print("terminal:", ti.name, "build", ti.build, "connected:", ti.connected, flush=True)
        mt5.shutdown()
        break
    time.sleep(5)
