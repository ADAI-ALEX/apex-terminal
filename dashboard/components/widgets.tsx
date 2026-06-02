"use client";

import type React from "react";
import type { AlgoState } from "@/lib/types";
import { LiveChart } from "./LiveChart";
import { UsageCost } from "./UsageCost";

// ── chrome ─────────────────────────────────────────────────────────────
export function WidgetFrame({
  code, title, onClose, children,
}: {
  code: string; title: string; onClose: () => void; children: React.ReactNode;
}) {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-md border border-border bg-bg2">
      <div className="widget-drag flex items-center justify-between border-b border-border bg-bg3 px-2 py-1">
        <span className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-gold">
          <span className="rounded bg-gold/15 px-1 py-0.5 text-[9px] text-gold">{code}</span>
          {title}
        </span>
        <button
          onClick={onClose}
          onMouseDown={(e) => e.stopPropagation()}
          title="Close"
          className="px-1 font-mono text-textdim transition hover:text-down"
        >
          ×
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">{children}</div>
    </div>
  );
}

// ── helpers ────────────────────────────────────────────────────────────
function money(v: number, ccy = "GBP"): string {
  const sym = ccy === "GBP" ? "£" : ccy === "USD" ? "$" : ccy === "EUR" ? "€" : "";
  return `${v < 0 ? "-" : ""}${sym}${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function Row({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  return (
    <div className="flex items-center justify-between border-b border-border/50 px-3 py-1.5">
      <span className="font-mono text-[10px] uppercase tracking-wider text-textdim">{label}</span>
      <span className={`font-bold ${tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-textmid"}`}>{value}</span>
    </div>
  );
}

// ── bodies ─────────────────────────────────────────────────────────────
function AccountBody({ state }: { state: AlgoState }) {
  const { account, pnl, stats } = state;
  const ccy = account.currency || "GBP";
  return (
    <div className="py-1">
      <Row label="Balance" value={money(account.balance, ccy)} />
      <Row label="Equity" value={money(account.equity, ccy)} />
      <Row label="Daily P&L" value={`${money(pnl.daily, ccy)} (${pnl.daily_pct >= 0 ? "+" : ""}${pnl.daily_pct.toFixed(2)}%)`} tone={pnl.daily >= 0 ? "up" : "down"} />
      <Row label="Weekly P&L" value={`${money(pnl.weekly, ccy)} (${pnl.weekly_pct >= 0 ? "+" : ""}${pnl.weekly_pct.toFixed(2)}%)`} tone={pnl.weekly >= 0 ? "up" : "down"} />
      <Row label="Win rate" value={`${stats.win_rate ?? 0}% · ${stats.trades ?? 0} trades`} />
      <Row label="Profit factor" value={String(stats.profit_factor ?? 0)} />
      <Row label="Open positions" value={String(state.positions.length)} />
      <Row label="Portfolio health" value={String(state.portfolio_health)} />
    </div>
  );
}

function PositionsBody({ state }: { state: AlgoState }) {
  const ps = state.positions;
  if (!ps.length) return <div className="p-6 text-center font-mono text-xs text-textdim">No open positions.</div>;
  return (
    <table className="w-full text-left font-mono text-[11px]">
      <thead className="sticky top-0 bg-bg2 text-[9px] uppercase tracking-wider text-textdim">
        <tr>{["Mkt", "Dir", "Size", "Entry", "Now", "P&L", "Strat"].map((h) => <th key={h} className="px-2 py-1.5">{h}</th>)}</tr>
      </thead>
      <tbody>
        {ps.map((p) => (
          <tr key={p.deal_id} className="border-t border-border">
            <td className="px-2 py-1 text-textmid">{p.market_key}</td>
            <td className={`px-2 py-1 ${p.direction === "BUY" ? "text-up" : "text-down"}`}>{p.direction}</td>
            <td className="px-2 py-1 text-textmid">£{p.size.toFixed(2)}</td>
            <td className="px-2 py-1 text-textmid">{p.entry_price}</td>
            <td className="px-2 py-1 text-textmid">{p.current_price}</td>
            <td className={`px-2 py-1 font-bold ${p.unrealised_pnl >= 0 ? "text-up" : "text-down"}`}>£{p.unrealised_pnl.toFixed(2)}</td>
            <td className="px-2 py-1 text-[9px] text-textmid">{p.strategy}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function WatchlistBody({ state }: { state: AlgoState }) {
  const markets = state.markets?.length ? state.markets : Object.keys(state.indicators ?? {});
  if (!markets.length) return <div className="p-6 text-center font-mono text-xs text-textdim">No instruments selected.</div>;
  return (
    <table className="w-full text-left font-mono text-[11px]">
      <thead className="sticky top-0 bg-bg2 text-[9px] uppercase tracking-wider text-textdim">
        <tr>{["Instrument", "Price", "RSI", "Regime"].map((h) => <th key={h} className="px-3 py-1.5">{h}</th>)}</tr>
      </thead>
      <tbody>
        {markets.map((m) => {
          const s = state.indicators?.[m];
          return (
            <tr key={m} className="border-t border-border">
              <td className="px-3 py-1.5 font-medium text-textmid">{m}</td>
              <td className="px-3 py-1.5 text-textmid">{s?.price?.toFixed(2) ?? "…"}</td>
              <td className="px-3 py-1.5 text-textmid">{s?.rsi?.toFixed(0) ?? "—"}</td>
              <td className={`px-3 py-1.5 ${s?.regime === "TRENDING" ? "text-up" : s?.regime === "VOLATILE" ? "text-down" : "text-gold"}`}>{s?.regime ?? "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function IndicatorsBody({ state }: { state: AlgoState }) {
  const markets = state.markets?.length ? state.markets : Object.keys(state.indicators ?? {});
  return (
    <table className="w-full text-left font-mono text-[11px]">
      <thead className="sticky top-0 bg-bg2 text-[9px] uppercase tracking-wider text-textdim">
        <tr>{["Mkt", "EMA9", "EMA21", "EMA55", "RSI", "ATR", "ADX"].map((h) => <th key={h} className="px-2 py-1.5">{h}</th>)}</tr>
      </thead>
      <tbody>
        {markets.map((m) => {
          const s = state.indicators?.[m];
          return (
            <tr key={m} className="border-t border-border text-textmid">
              <td className="px-2 py-1.5 font-medium">{m}</td>
              <td className="px-2 py-1.5">{s?.ema_fast?.toFixed(1) ?? "—"}</td>
              <td className="px-2 py-1.5">{s?.ema_mid?.toFixed(1) ?? "—"}</td>
              <td className="px-2 py-1.5">{s?.ema_slow?.toFixed(1) ?? "—"}</td>
              <td className="px-2 py-1.5">{s?.rsi?.toFixed(0) ?? "—"}</td>
              <td className="px-2 py-1.5">{s?.atr?.toFixed(2) ?? "—"}</td>
              <td className="px-2 py-1.5">{s?.adx?.toFixed(0) ?? "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function RiskBody({ state }: { state: AlgoState }) {
  const prop = state.prop;
  const breakers = state.breakers ?? {};
  return (
    <div className="space-y-3 p-3">
      {prop?.enabled ? (
        <>
          <DDBar label="Daily drawdown" value={prop.daily_dd_pct} limit={prop.daily_limit_pct} />
          <DDBar label="Total drawdown" value={prop.total_dd_pct} limit={prop.total_limit_pct} />
        </>
      ) : (
        <div className="font-mono text-[10px] text-textdim">Prop guard off (non-prop profile).</div>
      )}
      <div className="flex flex-wrap gap-1.5 pt-1">
        {Object.entries(breakers).map(([k, tripped]) => (
          <span key={k} className={`rounded px-2 py-0.5 font-mono text-[10px] ${tripped ? "bg-down/10 text-down" : "bg-up/10 text-up"}`}>{k}</span>
        ))}
      </div>
    </div>
  );
}
function DDBar({ label, value, limit }: { label: string; value: number; limit: number }) {
  const pct = Math.min(100, (value / limit) * 100);
  const tone = pct > 75 ? "bg-down" : pct > 50 ? "bg-gold" : "bg-up";
  return (
    <div>
      <div className="mb-1 flex justify-between font-mono text-[10px]">
        <span className="text-textdim uppercase tracking-wider">{label}</span>
        <span className="text-textmid">{value?.toFixed(2)}% / {limit}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded bg-bg3">
        <div className={`h-full ${tone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function LogBody({ state }: { state: AlgoState }) {
  const colour: Record<string, string> = { ERROR: "text-down", WARNING: "text-gold", INFO: "text-textmid", DEBUG: "text-textdim" };
  const ordered = [...(state.logs ?? [])].reverse();
  return (
    <div className="p-2 font-mono text-[11px] leading-relaxed">
      {ordered.length === 0 ? <div className="text-textdim">No log entries.</div> : ordered.map((l, i) => (
        <div key={i} className="flex gap-2 py-0.5">
          <span className="shrink-0 text-textdim">{new Date(l.time).toLocaleTimeString()}</span>
          <span className={`shrink-0 ${colour[l.level] ?? "text-textmid"}`}>{l.level.slice(0, 4)}</span>
          <span className="text-textmid">{l.message}</span>
        </div>
      ))}
    </div>
  );
}

// ── registry ───────────────────────────────────────────────────────────
export type WidgetDef = {
  id: string;
  code: string;       // 3-letter Bloomberg-style code
  name: string;
  category: string;
  w: number; h: number; minW: number; minH: number;
  render: (state: AlgoState) => React.ReactNode;
};

export const WIDGETS: WidgetDef[] = [
  { id: "chart", code: "PRC", name: "Price Chart", category: "MARKETS", w: 7, h: 13, minW: 4, minH: 8, render: (s) => <LiveChart state={s} /> },
  { id: "watchlist", code: "WAT", name: "Watchlist", category: "MARKETS", w: 5, h: 8, minW: 3, minH: 4, render: (s) => <WatchlistBody state={s} /> },
  { id: "account", code: "ACC", name: "Account Stats", category: "ACCOUNT", w: 5, h: 9, minW: 3, minH: 5, render: (s) => <AccountBody state={s} /> },
  { id: "positions", code: "POS", name: "Open Positions", category: "ACCOUNT", w: 7, h: 7, minW: 4, minH: 4, render: (s) => <PositionsBody state={s} /> },
  { id: "risk", code: "RSK", name: "Risk / Breakers", category: "RISK", w: 5, h: 7, minW: 3, minH: 4, render: (s) => <RiskBody state={s} /> },
  { id: "indicators", code: "IND", name: "Indicators", category: "ANALYTICS", w: 7, h: 8, minW: 4, minH: 4, render: (s) => <IndicatorsBody state={s} /> },
  { id: "usage", code: "AIU", name: "AI Usage / Cost", category: "AI", w: 4, h: 9, minW: 3, minH: 5, render: (s) => <UsageCost state={s} /> },
  { id: "log", code: "LOG", name: "System Log", category: "SYSTEM", w: 8, h: 8, minW: 4, minH: 4, render: (s) => <LogBody state={s} /> },
];

export const WIDGETS_BY_ID: Record<string, WidgetDef> = Object.fromEntries(WIDGETS.map((w) => [w.id, w]));

export const WIDGET_CATEGORIES: { name: string; items: WidgetDef[] }[] = (() => {
  const order = ["MARKETS", "ACCOUNT", "RISK", "ANALYTICS", "AI", "SYSTEM"];
  return order.map((name) => ({ name, items: WIDGETS.filter((w) => w.category === name) }));
})();
