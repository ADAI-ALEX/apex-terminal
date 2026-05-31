"use client";

import type { AlgoState } from "@/lib/types";

export function Overview({ state }: { state: AlgoState }) {
  const { account, pnl, stats } = state;
  const ccy = account.currency || "GBP";

  const cards = [
    { label: "Balance", value: money(account.balance, ccy) },
    { label: "Equity", value: money(account.equity, ccy) },
    {
      label: "Daily P&L",
      value: money(pnl.daily, ccy),
      sub: `${pnl.daily_pct >= 0 ? "+" : ""}${pnl.daily_pct.toFixed(2)}%`,
      tone: pnl.daily >= 0 ? "up" : "down",
    },
    {
      label: "Weekly P&L",
      value: money(pnl.weekly, ccy),
      sub: `${pnl.weekly_pct >= 0 ? "+" : ""}${pnl.weekly_pct.toFixed(2)}%`,
      tone: pnl.weekly >= 0 ? "up" : "down",
    },
    { label: "Win rate", value: `${stats.win_rate ?? 0}%`, sub: `${stats.trades ?? 0} trades` },
    {
      label: "Profit factor",
      value: Number.isFinite(stats.profit_factor) ? String(stats.profit_factor ?? 0) : "∞",
    },
    { label: "Open positions", value: String(state.positions.length) },
    { label: "Portfolio health", value: `${state.portfolio_health}` },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
      {cards.map((c) => (
        <div key={c.label} className="rounded-md border border-border bg-bg3 p-4">
          <div className="font-mono text-[9px] uppercase tracking-wider text-textdim">
            {c.label}
          </div>
          <div
            className={`mt-1 text-lg font-bold ${
              c.tone === "up" ? "text-up" : c.tone === "down" ? "text-down" : "text-gold"
            }`}
          >
            {c.value}
          </div>
          {c.sub && <div className="mt-0.5 font-mono text-[10px] text-textmid">{c.sub}</div>}
        </div>
      ))}
    </div>
  );
}

function money(v: number, ccy: string): string {
  const sign = v < 0 ? "-" : "";
  const symbol = ccy === "GBP" ? "£" : ccy === "USD" ? "$" : "";
  return `${sign}${symbol}${Math.abs(v).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
