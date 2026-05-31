"""loguru configuration — one place to configure all logging.

Call ``setup_logging()`` once at process start. Logs go to stderr (coloured) and
to a rotating file under ``logs/``. The dashboard's System Log panel reads the
ring buffer exposed by :func:`recent_logs`.
"""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

from loguru import logger

from apex.config import get_settings

_LOG_DIR = Path("logs")
_RING: deque[dict] = deque(maxlen=200)   # last N records for the dashboard


def _ring_sink(message) -> None:  # type: ignore[no-untyped-def]
    record = message.record
    _RING.append(
        {
            "time": record["time"].isoformat(),
            "level": record["level"].name,
            "message": record["message"],
            "module": record["module"],
        }
    )


def setup_logging() -> None:
    """Configure loguru sinks. Idempotent."""
    settings = get_settings()
    logger.remove()

    logger.add(
        sys.stderr,
        level=settings.log_level,
        colorize=True,
        format=(
            "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
            "<cyan>{module}</cyan> | <level>{message}</level>"
        ),
    )

    _LOG_DIR.mkdir(exist_ok=True)
    logger.add(
        _LOG_DIR / "apex_{time:YYYY-MM-DD}.log",
        level=settings.log_level,
        rotation="00:00",
        retention="14 days",
        enqueue=True,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module}:{function}:{line} | {message}",
    )

    logger.add(_ring_sink, level="INFO")
    logger.info("Logging initialised (level={})", settings.log_level)


def recent_logs(limit: int = 50) -> list[dict]:
    """Return the most recent log records (newest last) for the dashboard."""
    items = list(_RING)
    return items[-limit:]
