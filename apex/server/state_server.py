"""FastAPI mini-server exposing the algo's state to the dashboard.

Endpoints (all require the ``X-Apex-Secret`` header matching ``VPS_SECRET``,
except ``/health`` which only needs it for the detailed body):

* ``GET /health``  — liveness + position count + daily P&L.
* ``GET /state``   — the full SharedState snapshot the dashboard renders.

The dashboard's Next.js ``/api/stream`` route polls ``/state`` every ~3s and
re-streams it to the browser as Server-Sent Events.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from apex.config import get_settings
from apex.core.state import STATE
from apex.onboarding import service as onboarding
from apex.onboarding.schema import OnboardingPayload, OnboardingStatus, ValidationResponse
from apex.onboarding.store import STORE


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Apex Algo State Server", version="1.0.0")

    # The dashboard runs on a different origin (Vercel / localhost:3000).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    def _check_secret(secret: str | None) -> None:
        if secret != settings.vps_secret:
            raise HTTPException(status_code=401, detail="Bad or missing X-Apex-Secret")

    @app.get("/health")
    async def health(x_apex_secret: str | None = Header(default=None)) -> dict:
        snap = STATE.snapshot()
        body = {
            "status": "ok",
            "mode": snap["mode"],
            "algo_status": snap["status"],
            "configured": STORE.is_configured(),
        }
        if x_apex_secret == settings.vps_secret:
            body.update(
                positions=len(snap["positions"]),
                daily_pnl=snap["pnl"]["daily"],
                last_heartbeat=snap["last_heartbeat"],
            )
        return body

    @app.get("/state")
    async def state(x_apex_secret: str | None = Header(default=None)) -> dict:
        _check_secret(x_apex_secret)
        return STATE.snapshot()

    # ── Onboarding (the unconfigured-launch gate) ────────────────────────
    # /onboarding/status is intentionally unauthenticated: it carries no secrets
    # (booleans + masked hints only) and the dashboard must read it *before* it
    # knows whether the system is configured. Mutating routes require the secret.
    @app.get("/onboarding/status")
    async def onboarding_status() -> OnboardingStatus:
        return onboarding.current_status()

    @app.post("/onboarding/validate")
    async def onboarding_validate(
        payload: OnboardingPayload, x_apex_secret: str | None = Header(default=None)
    ) -> ValidationResponse:
        _check_secret(x_apex_secret)
        return await asyncio.to_thread(onboarding.validate, payload)

    @app.post("/onboarding/save")
    async def onboarding_save(
        payload: OnboardingPayload, x_apex_secret: str | None = Header(default=None)
    ) -> ValidationResponse:
        _check_secret(x_apex_secret)
        result = await asyncio.to_thread(onboarding.save, payload)
        if not result.ok:
            raise HTTPException(status_code=422, detail=result.model_dump())
        return result

    @app.post("/onboarding/reset")
    async def onboarding_reset(x_apex_secret: str | None = Header(default=None)) -> OnboardingStatus:
        _check_secret(x_apex_secret)
        STORE.clear()
        from apex.config import reload_settings
        from apex.onboarding.runtime import RUNTIME

        reload_settings()
        RUNTIME.reset()
        return onboarding.current_status()

    return app


async def serve(stop_event: asyncio.Event | None = None) -> None:
    """Run uvicorn inside the existing asyncio loop (alongside the heartbeat)."""
    import uvicorn

    settings = get_settings()
    config = uvicorn.Config(
        create_app(),
        host=settings.state_host,
        port=settings.state_port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()
