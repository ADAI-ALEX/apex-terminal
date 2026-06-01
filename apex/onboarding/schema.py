"""Pydantic schemas for the onboarding API (request + response payloads).

These are the boundary types the dashboard wizard POSTs and the state server
returns. Secrets are accepted inbound but **never** echoed back outbound — see
:class:`OnboardingStatus`, which only ever carries masked hints.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────
#  Inbound (wizard → state server)
# ──────────────────────────────────────────────────────────────────────────
class IGCredentialsIn(BaseModel):
    """IG Markets credentials. All optional — blank means PAPER/simulation mode."""

    acc_type: str = "DEMO"        # DEMO | LIVE
    username: str = ""
    password: str = ""
    api_key: str = ""
    account_id: str = ""

    @property
    def provided(self) -> bool:
        return bool(self.username and self.password and self.api_key)


class AnthropicCredentialsIn(BaseModel):
    """Claude API key. Optional — without it the algo runs on safe NO_TRADE defaults."""

    api_key: str = ""
    model: str = "claude-sonnet-4-6"

    @property
    def provided(self) -> bool:
        return bool(self.api_key)


class RiskProfileIn(BaseModel):
    """Non-secret trading configuration chosen in the wizard."""

    profile: str = "prop_ftmo"            # see config.RISK_PROFILES
    starting_equity: float = Field(default=100_000.0, gt=0)
    account_currency: str = "GBP"
    active_markets: list[str] = Field(default_factory=lambda: ["US500", "EURUSD"])
    daily_target_pct: float = 0.5
    trading_enabled: bool = False         # explicit opt-in; stays off until the user flips it


class OnboardingPayload(BaseModel):
    """Full wizard submission."""

    ig: IGCredentialsIn = Field(default_factory=IGCredentialsIn)
    anthropic: AnthropicCredentialsIn = Field(default_factory=AnthropicCredentialsIn)
    risk: RiskProfileIn = Field(default_factory=RiskProfileIn)


class SettingsUpdate(BaseModel):
    """Partial config update from the Settings page. Only provided fields change;
    blank secrets are ignored so existing keys are preserved."""

    ig: dict | None = None
    anthropic: dict | None = None
    risk: dict | None = None


# ──────────────────────────────────────────────────────────────────────────
#  Outbound (state server → wizard)
# ──────────────────────────────────────────────────────────────────────────
class FieldValidation(BaseModel):
    """Result of validating one credential set."""

    field: str                  # "ig" | "anthropic"
    ok: bool
    detail: str = ""


class ValidationResponse(BaseModel):
    ok: bool
    results: list[FieldValidation] = Field(default_factory=list)


class OnboardingStatus(BaseModel):
    """Gate state the dashboard reads to decide onboarding-vs-dashboard.

    Carries **no secrets** — only booleans and masked hints (e.g. ``"••••abcd"``).
    """

    configured: bool = False
    ig_connected: bool = False
    claude_enabled: bool = False
    claude_model: str = "claude-sonnet-4-6"
    ai_enabled: bool = True
    mode: str = "UNCONFIGURED"            # UNCONFIGURED | PAPER | DEMO | LIVE
    acc_type: str = "DEMO"
    risk_profile: str = "prop_ftmo"
    active_markets: list[str] = Field(default_factory=list)
    starting_equity: float = 0.0
    account_currency: str = "GBP"
    trading_enabled: bool = False
    masked: dict[str, str] = Field(default_factory=dict)   # field -> masked hint
    configured_at: str | None = None
