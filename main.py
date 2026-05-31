"""Apex Algo entry point.

Starts the FastAPI state server and the heartbeat orchestrator concurrently on a
single asyncio event loop. Ctrl-C triggers a clean shutdown.

    python main.py
"""

from __future__ import annotations

import asyncio
import signal

from loguru import logger

from apex.config import get_settings
from apex.core.heartbeat import Heartbeat
from apex.logging_setup import setup_logging
from apex.server.state_server import serve as serve_state


async def _amain() -> None:
    setup_logging()
    settings = get_settings()

    logger.info("=" * 56)
    logger.info("  APEX ALGO v1.0  | account={}  trading_enabled={}",
                settings.ig_acc_type.value, settings.trading_enabled)
    logger.info("  markets: {}", ", ".join(m.key for m in settings.active_markets()))
    logger.info("  Claude: {}  |  IG creds: {}",
                "on" if settings.has_anthropic_key else "off (safe defaults)",
                "yes" if settings.has_ig_credentials else "no (PAPER mode)")
    logger.info("=" * 56)

    if settings.is_live and settings.trading_enabled:
        logger.warning("⚠  LIVE account with trading ENABLED — real money at risk.")

    heartbeat = Heartbeat(settings=settings)

    stop = asyncio.Event()

    def _request_stop() -> None:
        logger.warning("Shutdown requested — stopping heartbeat...")
        heartbeat.stop()
        stop.set()

    # SIGINT/SIGTERM handling (best-effort on Windows).
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:  # Windows
            pass

    state_task = asyncio.create_task(serve_state(stop), name="state-server")
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
