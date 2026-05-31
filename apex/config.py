"""Central configuration — the single source of truth for every constant.

No magic numbers live in logic files: strategies, the risk engine, the heartbeat
and the IG client all read their parameters from here. Secrets are read from the
environment (loaded from ``.env`` via python-dotenv); everything else is declared
as typed dataclasses so the values are discoverable and overridable in tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache

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
#  Top-level settings (environment-driven)
# ──────────────────────────────────────────────────────────────────────────
def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # IG
    ig_acc_type: AccountType = field(
        default_factory=lambda: AccountType(os.getenv("IG_ACC_TYPE", "DEMO").upper())
    )
    ig_username: str = field(default_factory=lambda: os.getenv("IG_USERNAME", ""))
    ig_password: str = field(default_factory=lambda: os.getenv("IG_PASSWORD", ""))
    ig_api_key: str = field(default_factory=lambda: os.getenv("IG_API_KEY", ""))
    ig_account_id: str = field(default_factory=lambda: os.getenv("IG_ACCOUNT_ID", ""))

    # Claude
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    claude_model: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"))

    # State server
    state_host: str = field(default_factory=lambda: os.getenv("STATE_SERVER_HOST", "0.0.0.0"))
    state_port: int = field(default_factory=lambda: int(os.getenv("STATE_SERVER_PORT", "8080")))
    vps_secret: str = field(default_factory=lambda: os.getenv("VPS_SECRET", "change-me"))

    # Toggles
    trading_enabled: bool = field(default_factory=lambda: _env_bool("TRADING_ENABLED", True))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    # Sub-configs
    risk: RiskParams = field(default_factory=RiskParams)
    strategy: StrategyParams = field(default_factory=StrategyParams)
    heartbeat: HeartbeatParams = field(default_factory=HeartbeatParams)

    def active_markets(self) -> list[Market]:
        raw = os.getenv("ACTIVE_MARKETS", ",".join(MARKETS.keys()))
        keys = [k.strip().upper() for k in raw.split(",") if k.strip()]
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton (cached)."""
    return Settings()
