"""Onboarding service — status, validate, and save orchestration.

Sits between the state-server HTTP handlers and the encrypted :class:`ConfigStore`.
On a successful save it clears the cached :func:`apex.config.get_settings` singleton
and fires :data:`RUNTIME` so the supervisor in ``main.py`` starts the heartbeat
immediately. Validators are synchronous; callers run :func:`validate` / :func:`save`
in a worker thread.
"""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from apex.onboarding.runtime import RUNTIME
from apex.onboarding.schema import (
    OnboardingPayload,
    OnboardingStatus,
    ValidationResponse,
)
from apex.onboarding.store import STORE, ConfigStore
from apex.onboarding.validator import validate_anthropic, validate_ig


def current_status(store: ConfigStore | None = None) -> OnboardingStatus:
    """Build the gate state the dashboard polls (no secrets, masked hints only)."""
    store = store or STORE
    data = store.load()
    if not data:
        return OnboardingStatus(configured=False, mode="UNCONFIGURED")

    ig = data.get("ig", {})
    anth = data.get("anthropic", {})
    risk = data.get("risk", {})

    has_ig = bool(ig.get("username") and ig.get("password") and ig.get("api_key"))
    acc_type = (ig.get("acc_type") or "DEMO").upper()
    mode = acc_type if has_ig else "PAPER"

    masked = store.redacted()
    masked_hints = {
        "ig_api_key": masked.get("ig", {}).get("api_key", ""),
        "anthropic_api_key": masked.get("anthropic", {}).get("api_key", ""),
    }

    return OnboardingStatus(
        configured=store.is_configured(),
        ig_connected=has_ig,
        claude_enabled=bool(anth.get("api_key")),
        mode=mode,
        acc_type=acc_type,
        risk_profile=risk.get("profile", "prop_ftmo"),
        active_markets=risk.get("active_markets", []),
        starting_equity=float(risk.get("starting_equity", 0.0) or 0.0),
        account_currency=risk.get("account_currency", "GBP"),
        trading_enabled=bool(risk.get("trading_enabled", False)),
        masked=masked_hints,
        configured_at=data.get("configured_at"),
    )


def validate(payload: OnboardingPayload) -> ValidationResponse:
    """Validate credentials against the live broker / API without persisting."""
    results = [validate_ig(payload.ig), validate_anthropic(payload.anthropic)]
    return ValidationResponse(ok=all(r.ok for r in results), results=results)


def save(payload: OnboardingPayload, store: ConfigStore | None = None) -> ValidationResponse:
    """Validate, then persist encrypted, then unlock the heartbeat.

    If the user supplied credentials that fail validation we refuse to save — the
    onboarding cannot complete with broken keys.
    """
    store = store or STORE
    result = validate(payload)
    if not result.ok:
        logger.warning("Onboarding save rejected — validation failed.")
        return result

    record = {
        "ig": payload.ig.model_dump(),
        "anthropic": payload.anthropic.model_dump(),
        "risk": payload.risk.model_dump(),
        "configured_at": datetime.now(timezone.utc).isoformat(),
    }
    store.save(record)

    # Make the running process see the new config without a restart.
    try:
        from apex.config import reload_settings

        reload_settings()
    except Exception as exc:  # pragma: no cover
        logger.error("Could not reload settings after onboarding: {}", exc)

    RUNTIME.mark_configured()
    logger.info("Onboarding complete — profile={} markets={}",
                payload.risk.profile, ",".join(payload.risk.active_markets))
    return result
