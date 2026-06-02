// Mirror of the Python SharedState.snapshot() payload (apex/core/state.py).

export interface Account {
  balance: number;
  available: number;
  equity: number;
  currency: string;
  updated_at: string;
}

export interface PositionView {
  deal_id: string;
  market_key: string;
  epic: string;
  direction: "BUY" | "SELL";
  size: number;
  entry_price: number;
  stop_price: number;
  target_price: number;
  current_price: number;
  strategy: string;
  confidence: number;
  opened_at: string;
  unrealised_pnl: number;
  unrealised_points: number;
  stop_distance_remaining: number;
  target_distance_remaining: number;
}

export interface IndicatorSnapshot {
  market_key: string;
  price: number;
  ema_fast: number | null;
  ema_mid: number | null;
  ema_slow: number | null;
  rsi: number | null;
  atr: number | null;
  adx: number | null;
  regime: "TRENDING" | "RANGING" | "VOLATILE" | null;
}

export interface LogEntry {
  time: string;
  level: string;
  message: string;
  module: string;
}

export interface AlgoState {
  status: string;
  mode: string;
  trading_enabled: boolean;
  account: Account;
  positions: PositionView[];
  indicators: Record<string, IndicatorSnapshot>;
  pnl: { daily: number; weekly: number; daily_pct: number; weekly_pct: number };
  stats: {
    trades?: number;
    win_rate?: number;
    profit_factor?: number;
    total_pnl?: number;
    wins?: number;
    losses?: number;
  };
  breakers: Record<string, boolean>;
  prop?: {
    enabled: boolean;
    action: string;
    daily_dd_pct: number;
    total_dd_pct: number;
    daily_limit_pct: number;
    total_limit_pct: number;
    locked: boolean;
    reason: string;
  };
  broker_error?: string;
  ai_enabled?: boolean;
  claude_usage?: {
    calls: number;
    input_tokens: number;
    output_tokens: number;
    est_cost_usd: number;
  };
  candles?: Record<
    string,
    { time: number; open: number; high: number; low: number; close: number }[]
  >;
  markets?: string[];
  daily_history?: { date: string; pnl: number; trades: number }[];
  portfolio_health: number;
  api_calls: Record<string, number>;
  last_heartbeat: string;
  logs: LogEntry[];
  server_time: string;
}
