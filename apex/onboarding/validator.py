"""Credential validators used by the onboarding 'Test connection' step.

Both functions are **synchronous** and network-bound; the state-server endpoints
call them via ``asyncio.to_thread`` so the event loop is never blocked. They never
raise — every failure path returns a :class:`FieldValidation` with ``ok=False`` and
a human-readable ``detail`` the wizard can show inline.
"""

from __future__ import annotations

from loguru import logger

from apex.onboarding.schema import (
    AnthropicCredentialsIn,
    FieldValidation,
    IGCredentialsIn,
)


def validate_ig(creds: IGCredentialsIn) -> FieldValidation:
    """Attempt a real IG session. Blank creds → PAPER mode (valid, not connected)."""
    if not creds.provided:
        return FieldValidation(
            field="ig",
            ok=True,
            detail="No IG credentials — running in PAPER (simulation) mode.",
        )

    acc_type = (creds.acc_type or "DEMO").upper()
    if acc_type not in {"DEMO", "LIVE"}:
        return FieldValidation(field="ig", ok=False, detail="acc_type must be DEMO or LIVE.")

    try:
        from trading_ig import IGService  # lazy import
    except Exception:
        return FieldValidation(
            field="ig",
            ok=False,
            detail="`trading-ig` is not installed on the server (pip install trading-ig).",
        )

    try:
        svc = IGService(
            creds.username,
            creds.password,
            creds.api_key,
            acc_type.lower(),
            acc_number=creds.account_id or None,
        )
        svc.create_session()
        accounts = svc.fetch_accounts()
        n = len(accounts) if accounts is not None else 0
        logger.info("IG validation OK ({}, {} account(s)).", acc_type, n)
        return FieldValidation(
            field="ig",
            ok=True,
            detail=f"Connected to IG {acc_type} — {n} account(s) found.",
        )
    except Exception as exc:
        msg = str(exc) or exc.__class__.__name__
        logger.warning("IG validation failed: {}", msg)
        return FieldValidation(field="ig", ok=False, detail=f"IG rejected the credentials: {msg}")


def validate_anthropic(creds: AnthropicCredentialsIn) -> FieldValidation:
    """Validate the Claude key with a minimal 1-token message. Blank → safe defaults."""
    if not creds.provided:
        return FieldValidation(
            field="anthropic",
            ok=True,
            detail="No Claude key — agents disabled; the algo uses safe NO_TRADE defaults.",
        )

    if not creds.api_key.startswith("sk-ant-"):
        return FieldValidation(
            field="anthropic",
            ok=False,
            detail="That does not look like an Anthropic key (expected an 'sk-ant-' prefix).",
        )

    try:
        from anthropic import Anthropic  # lazy import
    except Exception:
        return FieldValidation(
            field="anthropic",
            ok=False,
            detail="`anthropic` SDK is not installed on the server (pip install anthropic).",
        )

    try:
        client = Anthropic(api_key=creds.api_key)
        client.messages.create(
            model=creds.model or "claude-sonnet-4-6",
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        logger.info("Anthropic validation OK ({}).", creds.model)
        return FieldValidation(field="anthropic", ok=True, detail=f"Claude key OK ({creds.model}).")
    except Exception as exc:
        msg = str(exc) or exc.__class__.__name__
        logger.warning("Anthropic validation failed: {}", msg)
        return FieldValidation(field="anthropic", ok=False, detail=f"Claude rejected the key: {msg}")
