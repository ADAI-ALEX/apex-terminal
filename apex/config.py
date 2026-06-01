"""Central configuration — the single source of truth for every constant.

No magic numbers live in logic files: strategies, the risk engine, the heartbeat
and the IG client all read their parameters from here.

Two configuration sources, in precedence order:

1. **Environment** (loaded from ``.env`` via python-dotenv) — used on a VPS / CI.
2. **Encrypted onboarding store** (``apex/onboarding/store.py``) — written by the
   Web-UI wizard. Overlaid only where the environment leaves a value blank.

This lets the process **launch with zero configuration** (the onboarding state):
nothing here raises if credentials are missing — the system simply reports
``onboarding_complete == False`` and the heartbeat stays locked until the UI
completes onboarding. Everything else is declared as typed dataclasses so values
are discoverable and overridable in tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv

load_dotenv()  # populate os.environ from .env if present (no-op in prod with real env)


# ──────────────────────────────────────────────────────────────────────────
#  Enums
# ──────────────────────────────────────────────────────────────────────────
class AccountType(str, Enum):
    DEMO = "DEMO"
    LIVE = "LIVE"


class Regime(str, Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


# ──────────────────────────────────────────────────────────────────────────
#  Markets (IG spread-bet DFB EPICs) — verify with GET /markets?searchTerm=...
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Market:
    key: str                 # internal key used in env / code
    name: str                # human label
    epic: str                # IG EPIC (spread bet, .IP suffix)
    point_value: float       # £ per point per £1/pt stake (always 1.0 for spread bets)
    fca_leverage: int        # FCA retail leverage cap
    open_utc: str            # session open (UK local, informational)
    close_utc: str           # session close
    preferred_regime: Regime
    min_stop_points: float   # broker minimum stop distance, points


MARKETS: dict[str, Market] = {
    "FTSE100": Market("FTSE100", "FTSE 100", "IX.D.FTSE.DAILY.IP", 1.0, 20, "08:00", "16:30", Regime.TRENDING, 8.0),
    "US500":   Market("US500", "US 500 (S&P)", "IX.D.SPTRD.DAILY.IP", 1.0, 20, "14:30", "21:00", Regime.TRENDING, 4.0),
    "NAS100":  Market("NAS100", "US Tech 100 (Nasdaq)", "IX.D.NASDAQ.DAILY.IP", 1.0, 20, "14:30", "21:00", Regime.VOLATILE, 6.0),
    "DAX40":   Market("DAX40", "Germany 40 (DAX)", "IX.D.DAX.DAILY.IP", 1.0, 20, "08:00", "16:30", Regime.VOLATILE, 8.0),
    "EURUSD":  Market("EURUSD", "EUR/USD", "CS.D.EURUSD.MINI.IP", 1.0, 30, "07:00", "17:00", Regime.RANGING, 6.0),
    "GBPUSD":  Market("GBPUSD", "GBP/USD", "CS.D.GBPUSD.MINI.IP", 1.0, 30, "07:00", "17:00", Regime.RANGING, 6.0),
}


# ──────────────────────────────────────────────────────────────────────────
#  Risk parameters (Section 03 + Section 06)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RiskParams:
    # Position sizing
    max_risk_per_trade_pct: float = 2.0    # % of account risked per trade
    max_total_open_risk_pct: float = 6.0   # % of account across all open positions
    max_effective_leverage: float = 5.0    # cap on notional / equity
    single_trade_risk_cap_pct: float = 5.0 # hard ceiling — never risk more than this on one position
    min_stake_per_point: float = 0.50      # IG minimum, £/pt
    atr_stop_multiplier: float = 1.5       # stop distance = ATR14 * this
    default_rr: float = 1.6                # fallback reward:risk if strategy omits it

    # Circuit breakers
    daily_loss_limit_pct: float = -5.0     # block new entries for the day
    weekly_loss_limit_pct: float = -10.0   # full halt, manual restart
    max_concurrent_positions: int = 3
    consecutive_loss_trigger: int = 4      # losses in a row
    consecutive_loss_size_factor: float = 0.5
    consecutive_loss_cooldown_trades: int = 10
    news_blackout_minutes: int = 30        # before a major macro event
    overnight_cutoff_uk: str = "22:00"     # close low-conviction positions
    overnight_min_profit_points: float = 20.0
    market_close_buffer_minutes: int = 15  # flatten instrument before close


# ──────────────────────────────────────────────────────────────────────────
#  Prop-firm safeties (PROP_FIRM_PLAN Step 4) — equity-drawdown circuit breaker
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PropFirmParams:
    enabled: bool = False
    daily_dd_limit_pct: float = 3.0        # max daily floating-equity drawdown (positive %)
    total_dd_limit_pct: float = 8.0        # max total drawdown from the high-water peak
    circuit_buffer_pct: float = 0.5        # liquidate when within this of a limit
    daily_reset_hour: int = 17             # prop daily reset (local to daily_reset_tz)
    daily_reset_tz: str = "America/New_York"  # 17:00 NY ≈ standard prop reset
    equity_poll_seconds: int = 1           # floating-equity sampling cadence


@dataclass(frozen=True)
class ProfileSpec:
    """A named bundle of (risk, prop) parameters selectable during onboarding."""

    label: str
    risk: RiskParams
    prop: PropFirmParams


#: Selectable risk profiles. ``ig_standard`` MUST equal the bare ``RiskParams()``
#: defaults so existing behaviour / tests are unchanged.
RISK_PROFILES: dict[str, ProfileSpec] = {
    "ig_standard": ProfileSpec(
        label="IG Standard (2% risk, −5% daily)",
        risk=RiskParams(),
        prop=PropFirmParams(enabled=False),
    ),
    "prop_ftmo": ProfileSpec(
        label="Prop Firm — Conservative (FTMO/The5ers style)",
        risk=RiskParams(
            max_risk_per_trade_pct=0.4,        # 0.4% per trade (PROP_FIRM_PLAN §1.3)
            max_total_open_risk_pct=1.5,       # tiny aggregate floating risk
            single_trade_risk_cap_pct=1.0,
            max_effective_leverage=5.0,
            atr_stop_multiplier=1.5,
            default_rr=1.8,
            daily_loss_limit_pct=-2.0,         # block NEW entries at −2% (soft, before breaker)
            weekly_loss_limit_pct=-6.0,
            max_concurrent_positions=3,
            consecutive_loss_trigger=3,        # throttle sooner under prop rules
        ),
        prop=PropFirmParams(
            enabled=True,
            daily_dd_limit_pct=3.0,
            total_dd_limit_pct=8.0,
            circuit_buffer_pct=0.5,
            daily_reset_hour=17,
            daily_reset_tz="America/New_York",
        ),
    ),
}


def resolve_profile(name: str) -> ProfileSpec:
    """Return the named profile, falling back to ig_standard for unknown names."""
    return RISK_PROFILES.get(name, RISK_PROFILES["ig_standard"])


# ──────────────────────────────────────────────────────────────────────────
#  Strategy parameters (Section 01)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class StrategyParams:
    # EMA Trend Confluence
    ema_fast: int = 9
    ema_mid: int = 21
    ema_slow: int = 55
    ema_rsi_floor: float = 45.0
    ema_rsi_ceiling: float = 70.0
    ema_target_rr: float = 1.6

    # RSI Mean Reversion
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    reversion_target_rr: float = 1.1

    # ATR Breakout
    atr_period: int = 14
    breakout_compression_candles: int = 3
    breakout_compression_pctile: float = 0.35   # ATR below this percentile = compressed
    breakout_target_rr: float = 2.5

    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # Regime detector
    adx_period: int = 14
    adx_trend_threshold: float = 25.0    # ADX above => trending
    adx_range_threshold: float = 20.0    # ADX below => ranging
    atr_roc_volatile_pct: float = 0.25   # ATR rate-of-change above => volatile


# ──────────────────────────────────────────────────────────────────────────
#  Heartbeat cadences (Section 04), in seconds
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class HeartbeatParams:
    tier1_price_seconds: int = 30
    tier2_signal_seconds: int = 300
    tier3_portfolio_seconds: int = 1800
    health_seconds: int = 300
    candle_minutes_default: int = 5
    history_candles: int = 200   # how many candles to keep in memory per instrument


# ──────────────────────────────────────────────────────────────────────────
#  Config sources: environment first, encrypted onboarding store second
# ──────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _overlay() -> dict[str, Any]:
    """Load the decrypted onboarding config once (cached). Empty if unconfigured."""
    try:
        from apex.onboarding.store import STORE

        return STORE.load() or {}
    except Exception:
        return {}


def _ov(section: str, key: str, default: Any = None) -> Any:
    sec = _overlay().get(section) or {}
    val = sec.get(key)
    return val if val not in (None, "") else default


def _cfg_str(env_key: str, section: str, key: str, default: str = "") -> str:
    raw = os.getenv(env_key)
    if raw is not None and raw.strip() != "":
        return raw.strip()
    return str(_ov(section, key, default))


def _cfg_bool(env_key: str, section: str, key: str, default: bool) -> bool:
    raw = os.getenv(env_key)
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    val = _ov(section, key, None)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _cfg_float(env_key: str, section: str, key: str, default: float) -> float:
    try:
        return float(_cfg_str(env_key, section, key, str(default)))
    except (TypeError, ValueError):
        return default


# ──────────────────────────────────────────────────────────────────────────
#  Top-level settings
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class Settings:
    # IG
    ig_acc_type: AccountType = field(
        default_factory=lambda: _safe_acc_type(_cfg_str("IG_ACC_TYPE", "ig", "acc_type", "DEMO"))
    )
    ig_username: str = field(default_factory=lambda: _cfg_str("IG_USERNAME", "ig", "username"))
    ig_password: str = field(default_factory=lambda: _cfg_str("IG_PASSWORD", "ig", "password"))
    ig_api_key: str = field(default_factory=lambda: _cfg_str("IG_API_KEY", "ig", "api_key"))
    ig_account_id: str = field(default_factory=lambda: _cfg_str("IG_ACCOUNT_ID", "ig", "account_id"))

    # Claude
    anthropic_api_key: str = field(default_factory=lambda: _cfg_str("ANTHROPIC_API_KEY", "anthropic", "api_key"))
    claude_model: str = field(
        default_factory=lambda: _cfg_str("CLAUDE_MODEL", "anthropic", "model", "claude-sonnet-4-6")
    )

    # State server
    state_host: str = field(default_factory=lambda: _cfg_str("STATE_SERVER_HOST", "_", "_", "0.0.0.0"))
    state_port: int = field(default_factory=lambda: int(_cfg_str("STATE_SERVER_PORT", "_", "_", "8080")))
    vps_secret: str = field(default_factory=lambda: _cfg_str("VPS_SECRET", "_", "_", "change-me"))

    # Account / profile (chosen during onboarding)
    risk_profile: str = field(default_factory=lambda: _cfg_str("APEX_RISK_PROFILE", "risk", "profile", "ig_standard"))
    starting_equity: float = field(default_factory=lambda: _cfg_float("APEX_STARTING_EQUITY", "risk", "starting_equity", 0.0))
    account_currency: str = field(default_factory=lambda: _cfg_str("APEX_ACCOUNT_CURRENCY", "risk", "account_currency", "GBP"))
    daily_target_pct: float = field(default_factory=lambda: _cfg_float("APEX_DAILY_TARGET_PCT", "risk", "daily_target_pct", 0.5))

    # Toggles
    trading_enabled: bool = field(default_factory=lambda: _cfg_bool("TRADING_ENABLED", "risk", "trading_enabled", True))
    # Master AI brain switch. When False, NO Claude calls are ever made (agents return
    # safe NO_TRADE defaults). Lets the user run a pure-Python, zero-AI-cost system.
    ai_enabled: bool = field(default_factory=lambda: _cfg_bool("AI_ENABLED", "anthropic", "enabled", True))
    log_level: str = field(default_factory=lambda: _cfg_str("LOG_LEVEL", "_", "_", "INFO").upper())

    # Sub-configs — risk/prop are resolved from risk_profile in __post_init__.
    risk: RiskParams = field(default_factory=RiskParams)
    prop: PropFirmParams = field(default_factory=PropFirmParams)
    strategy: StrategyParams = field(default_factory=StrategyParams)
    heartbeat: HeartbeatParams = field(default_factory=HeartbeatParams)

    def __post_init__(self) -> None:
        spec = resolve_profile(self.risk_profile)
        self.risk = spec.risk
        self.prop = spec.prop

    def active_markets(self) -> list[Market]:
        raw = os.getenv("ACTIVE_MARKETS")
        if raw:
            keys = [k.strip().upper() for k in raw.split(",") if k.strip()]
        else:
            ov = _ov("risk", "active_markets")
            if isinstance(ov, list) and ov:
                keys = [str(k).strip().upper() for k in ov]
            else:
                keys = list(MARKETS.keys())
        return [MARKETS[k] for k in keys if k in MARKETS]

    @property
    def is_live(self) -> bool:
        return self.ig_acc_type is AccountType.LIVE

    @property
    def has_ig_credentials(self) -> bool:
        return bool(self.ig_username and self.ig_password and self.ig_api_key)

    @property
    def has_anthropic_key(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def onboarding_complete(self) -> bool:
        """True once the system has enough config to start the heartbeat.

        Satisfied by env-provided IG creds (VPS path), a persisted onboarding
        record (UI path, including explicit PAPER mode), or the dev escape hatch.
        """
        if _env_bool("APEX_SKIP_ONBOARDING", False):
            return True
        if self.has_ig_credentials:
            return True
        try:
            from apex.onboarding.store import STORE

            return STORE.is_configured()
        except Exception:
            return False


def _safe_acc_type(value: str) -> AccountType:
    try:
        return AccountType(value.upper())
    except ValueError:
        return AccountType.DEMO


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton (cached)."""
    return Settings()


def reload_settings() -> None:
    """Drop the cached overlay + Settings so the next read picks up new config.

    Called after the onboarding wizard saves, and by tests for isolation.
    """
    _overlay.cache_clear()
    get_settings.cache_clear()
