"""Runtime signals shared between the state server and the main supervisor.

The state server (FastAPI) and the supervisor in ``main.py`` run on the same
asyncio loop. When the onboarding ``save`` endpoint succeeds it calls
:meth:`RuntimeSignals.mark_configured`, which sets an :class:`asyncio.Event` the
supervisor is awaiting — so the trading heartbeat starts the moment the user
finishes onboarding, with no restart and no polling.
"""

from __future__ import annotations

import asyncio


class RuntimeSignals:
    def __init__(self) -> None:
        self._configured = asyncio.Event()

    @property
    def is_configured(self) -> bool:
        return self._configured.is_set()

    def mark_configured(self) -> None:
        self._configured.set()

    def reset(self) -> None:
        self._configured.clear()

    async def wait_configured(self) -> None:
        await self._configured.wait()


# Process-wide singleton.
RUNTIME = RuntimeSignals()
