"""IPC isolation probe: can the MetaTrader5 lib attach to the terminal AT ALL
(no login)? Tries portable mode first, then standard. Run inside Wine Python."""
import time

import MetaTrader5 as mt5

PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

for portable in (True, False):
    t0 = time.time()
    ok = mt5.initialize(PATH, portable=portable, timeout=90_000)
    dt = time.time() - t0
    print(f"portable={portable} -> INIT={ok} err={mt5.last_error()} ({dt:.0f}s)", flush=True)
    if ok:
        ti = mt5.terminal_info()
        print("terminal:", ti.name, "build", ti.build, "connected:", ti.connected, flush=True)
        mt5.shutdown()
        break
    time.sleep(5)
