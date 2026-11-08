# FTMO / MetaTrader 5 deployment

Runs Apex strategies against an FTMO demo account from a small Linux VM. MetaTrader 5
runs under Wine and headless Xvfb; `ApexBridge.mq5` exposes it to native Python
processes over a file bridge. All orders go through `apex_mt5.py`.

The strategy files themselves are private and are not in this repository. Copy your
own legs to `~/apex-v4/` before launching: `remote/run_leg.sh` and
`remote/respawn_legs.sh` name the two it starts.

## Contents

| Path | Purpose |
| --- | --- |
| `apex_mt5.py` | Shared MT5 execution engine |
| `mt5_filebridge.py`, `ApexBridge.mq5` | Python-to-MT5 file bridge and its Expert Advisor |
| `.env.template` | Account settings; copy to `~/apex-v4/.env` and never commit it |
| `remote/` | VM provisioning and launch scripts |
| `console/` | Local web console that monitors the VM over SSH |

The bridge runs on Windows Python 3.10 inside Wine, so code here must stay 3.10-compatible.

## Provisioning

Run in order on the VM, from `~/apex-v4/remote/`:

1. `01_swap.sh`: 2 GB swapfile for a 1 GB VM
2. `02_xvfb.sh`: Xvfb, tmux and winbind
3. `03_mt5_install.sh`: official MetaTrader 5 installer under Xvfb. `03d_mt5_final.sh` is the fully headless alternative.
4. `04_winpython.sh`: Windows Python inside the Wine prefix. `07_pyembed.sh` is the alternative that uses the embeddable zip.
5. `05_pip.sh`: `MetaTrader5` and numpy for that Python
6. `install_ftmo_servers.sh`: installs FTMO's server records (`servers.dat`)

## Launch

```bash
cp ~/apex-v4/.env.template ~/apex-v4/.env   # then fill in the account details
bash ~/apex-v4/remote/launch_all.sh
tmux attach -t apex
bash ~/apex-v4/remote/verify_live.sh        # health check
```

## Notes

- FTMO server time is EET: set `SERVER_UTC_OFFSET_HOURS` to 3 in summer and 2 in winter.
- Symbol names vary by FTMO server, so check Market Watch.
