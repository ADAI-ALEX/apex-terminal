"""Apex Algo entry point.

Boot sequence:

1. Always start the FastAPI **state server** — this serves the dashboard and the
   onboarding API, so the Web UI is reachable even with **zero** configuration.
2. If onboarding is incomplete, stay in the **ONBOARDING** state and wait. The
   moment the wizard's ``/onboarding/save`` succeeds it fires ``RUNTIME``, the
   supervisor reloads settings, and only *then* does the trading heartbeat start.
3. Run the heartbeat + state server concurrently until Ctrl-C.

    python main.py
"""

from __future__ import annotations

import asyncio
import signal

from loguru import logger

from apex.config import get_settings, reload_settings
from apex.core.heartbeat import Heartbeat
from apex.core.state import STATE
from apex.logging_setup import setup_logging
from apex.onboarding.runtime import RUNTIME
from apex.onboarding.store import STORE
from apex.server.state_server import serve as serve_state


async def _await_onboarding(stop: asyncio.Event) -> None:
    """Block until onboarding completes (via the UI) or shutdown is requested."""
    while not RUNTIME.is_configured and not stop.is_set():
        done, _ = await asyncio.wait(
            {asyncio.create_task(RUNTIME.wait_configured()), asyncio.create_task(stop.wait())},
            timeout=5.0,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            task.cancel()
        # Pick up config written out-of-band (e.g. env edit + file present).
        if STORE.is_configured():
            RUNTIME.mark_configured()


async def _amain() -> None:
    setup_logging()
    settings = get_settings()

    logger.info("=" * 56)
    logger.info("  APEX ALGO v1.1  | account={}  profile={}",
                settings.ig_acc_type.value, settings.risk_profile)
    logger.info("  Claude: {}  |  IG creds: {}  |  prop guard: {}",
                "on" if settings.has_anthropic_key else "off (safe defaults)",
                "yes" if settings.has_ig_credentials else "no (PAPER mode)",
                "ON" if settings.prop.enabled else "off")
    logger.info("=" * 56)

    stop = asyncio.Event()

    def _request_stop() -> None:
        logger.warning("Shutdown requested — stopping...")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:  # Windows
            pass

    # 1) State server is always up so the onboarding UI is reachable.
    state_task = asyncio.create_task(serve_state(stop), name="state-server")

    # 2) Gate the trading engine behind onboarding completion.
    if not settings.onboarding_complete:
        logger.warning("Unconfigured — awaiting Web-UI onboarding (state server on :{}).",
                       settings.state_port)
        STATE.update(status="ONBOARDING", mode="UNCONFIGURED", trading_enabled=False)
        await _await_onboarding(stop)
        reload_settings()
        settings = get_settings()
    else:
        RUNTIME.mark_configured()

    if stop.is_set():
        state_task.cancel()
        logger.info("Apex Algo stopped before onboarding completed.")
        return

    if settings.is_live and settings.trading_enabled:
        logger.warning("⚠  LIVE account with trading ENABLED — real money at risk.")
    logger.info("Onboarding complete — starting heartbeat (profile={}, markets: {}).",
                settings.risk_profile, ", ".join(m.key for m in settings.active_markets()))

    # In cloud-relay mode, confirm to the dashboard that the algo picked up the config.
    from apex.cloud import kv
    if kv.kv_enabled():
        from apex.onboarding import service
        kv.kv_set(kv.STATUS_KEY, service.current_status().model_dump())

    # 3) Start the trading heartbeat.
    heartbeat = Heartbeat(settings=settings)

    def _stop_heartbeat() -> None:
        heartbeat.stop()
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop_heartbeat)
        except NotImplementedError:  # Windows
            pass

    hb_task = asyncio.create_task(heartbeat.run(), name="heartbeat")
    try:
        await hb_task
    except asyncio.CancelledError:
        pass
    finally:
        state_task.cancel()
        heartbeat.journal.close()
        logger.info("Apex Algo stopped.")


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
