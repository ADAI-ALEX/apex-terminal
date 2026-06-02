"use client";

import { useEffect, useState } from "react";
import type React from "react";
import type { AlgoState } from "@/lib/types";
import { LiveChart } from "./LiveChart";
import { UsageCost } from "./UsageCost";

// ── chrome ─────────────────────────────────────────────────────────────
export function WidgetFrame({
  code, title, onClose, onMaximize, maximized, onBodyPointerDown, children,
}: {
  code: string; title: string; onClose: () => void;
  onMaximize?: () => void; maximized?: boolean;
  onBodyPointerDown?: (e: React.MouseEvent) => void;
  children: React.ReactNode;
}) {
  const stop = (e: React.MouseEvent) => e.stopPropagation();
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-border bg-bg2">
      <div className="widget-drag flex items-center justify-between border-b border-border bg-bg3 px-2.5 py-1.5">
        <span className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-gold">
          <span className="rounded bg-gold/15 px-1 py-0.5 text-[9px] text-gold">{code}</span>
          {title}
        </span>
        <span className="flex items-center gap-0.5">
          {onMaximize && (
            <button onClick={onMaximize} onMouseDown={stop} title={maximized ? "Restore" : "Maximize"}
              className="px-1 font-mono text-textdim transition hover:text-gold">
              {maximized ? "❐" : "⤢"}
            </button>
          )}
          <button onClick={onClose} onMouseDown={stop} title="Close"
            className="px-1 font-mono text-textdim transition hover:text-down">×</button>
        </span>
      </div>
      {/* nodrag/nowheel: scroll, click, and zoom charts without the canvas
          dragging/zooming underneath. */}
      <div className="nodrag nowheel min-h-0 flex-1 overflow-auto" onMouseDown={onBodyPointerDown}>
        {children}
      </div>
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

type Quote = { price: number | null; changePct: number | null };

function WatchlistBody({ state }: { state: AlgoState }) {
  const markets = state.markets?.length ? state.markets : Object.keys(state.indicators ?? {});
  const symKey = markets.join(",");
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});

  useEffect(() => {
    if (!markets.length) return;
    let alive = true;
    const load = async () => {
      try {
        const res = await fetch(`/api/quote?symbols=${encodeURIComponent(symKey)}`, { cache: "no-store" });
        const j = await res.json();
        if (!alive) return;
        const map: Record<string, Quote> = {};
        for (const q of j.quotes ?? []) map[q.symbol] = { price: q.price, changePct: q.changePct };
        setQuotes(map);
      } catch { /* keep last */ }
    };
    void load();
    const id = setInterval(load, 30_000);
    return () => { alive = false; clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symKey]);

  if (!markets.length) return <div className="p-6 text-center font-mono text-xs text-textdim">No instruments selected.</div>;

  return (
    <table className="w-full text-left font-mono text-[11px]">
      <thead className="sticky top-0 bg-bg2 text-[9px] uppercase tracking-wider text-textdim">
        <tr>{["Instrument", "Price", "Chg%", "Regime"].map((h) => <th key={h} className="px-3 py-1.5">{h}</th>)}</tr>
      </thead>
      <tbody>
        {markets.map((m) => {
          const s = state.indicators?.[m];
          const q = quotes[m];
          const price = q?.price ?? s?.price ?? null;
          const chg = q?.changePct ?? null;
          const tone = chg == null ? "text-textdim" : chg >= 0 ? "text-up" : "text-down";
          return (
            <tr key={m} className="border-t border-border">
              <td className="px-3 py-1.5 font-medium text-textmid">{m}</td>
              <td className="px-3 py-1.5 text-textmid">{price != null ? price.toLocaleString(undefined, { maximumFractionDigits: price < 10 ? 4 : 2 }) : "…"}</td>
              <td className={`px-3 py-1.5 font-bold ${tone}`}>{chg != null ? `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%` : "…"}</td>
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

function CalculatorBody() {
  const [current, setCurrent] = useState("0");
  const [previous, setPrevious] = useState<number | null>(null);
  const [op, setOp] = useState<string | null>(null);
  const [overwrite, setOverwrite] = useState(true);

  const fmt = (n: number) => {
    if (!Number.isFinite(n)) return "Error";
    const s = Math.abs(n) >= 1e12 || (Math.abs(n) < 1e-6 && n !== 0) ? n.toExponential(6) : String(+n.toPrecision(12));
    return s;
  };
  const calc = (a: number, b: number, o: string) =>
    o === "+" ? a + b : o === "−" ? a - b : o === "×" ? a * b : o === "÷" ? a / b : b;

  const inputDigit = (d: string) => {
    setCurrent((c) => (overwrite ? d : c === "0" ? d : c + d));
    setOverwrite(false);
  };
  const inputDot = () => {
    setCurrent((c) => (overwrite ? "0." : c.includes(".") ? c : c + "."));
    setOverwrite(false);
  };
  const chooseOp = (o: string) => {
    const cur = parseFloat(current);
    if (previous != null && op && !overwrite) {
      const r = calc(previous, cur, op);
      setPrevious(r); setCurrent(fmt(r));
    } else {
      setPrevious(cur);
    }
    setOp(o); setOverwrite(true);
  };
  const equals = () => {
    if (previous == null || op == null) return;
    const r = calc(previous, parseFloat(current), op);
    setCurrent(fmt(r)); setPrevious(null); setOp(null); setOverwrite(true);
  };
  const clearAll = () => { setCurrent("0"); setPrevious(null); setOp(null); setOverwrite(true); };
  const backspace = () => setCurrent((c) => (overwrite || c.length <= 1 ? "0" : c.slice(0, -1)));
  const percent = () => { setCurrent((c) => fmt(parseFloat(c) / 100)); setOverwrite(true); };
  const negate = () => setCurrent((c) => fmt(-parseFloat(c)));

  // Keyboard support.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const k = e.key;
      if (k >= "0" && k <= "9") inputDigit(k);
      else if (k === ".") inputDot();
      else if (k === "+") chooseOp("+");
      else if (k === "-") chooseOp("−");
      else if (k === "*") chooseOp("×");
      else if (k === "/") { e.preventDefault(); chooseOp("÷"); }
      else if (k === "Enter" || k === "=") { e.preventDefault(); equals(); }
      else if (k === "Backspace") backspace();
      else if (k === "Escape") clearAll();
      else if (k === "%") percent();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const Key = ({ label, onClick, kind, span }: { label: string; onClick: () => void; kind?: "op" | "eq" | "fn"; span?: boolean }) => (
    <button
      onClick={onClick}
      className={`flex items-center justify-center rounded-md font-mono text-[clamp(13px,2.2vw,18px)] transition active:scale-[0.97] ${span ? "col-span-2" : ""} ${
        kind === "eq" ? "bg-gold text-black hover:bg-gold2"
          : kind === "op" ? "bg-gold/15 text-gold hover:bg-gold/25"
          : kind === "fn" ? "bg-bg3 text-down/80 hover:text-down"
          : "bg-bg3 text-textmid hover:text-gold"
      }`}
    >{label}</button>
  );

  return (
    <div className="flex h-full flex-col gap-2 p-2.5">
      <div className="flex flex-col justify-end rounded-md border border-border bg-bg px-3 py-2 text-right">
        <div className="h-4 truncate font-mono text-[11px] text-textdim">{previous != null ? `${fmt(previous)} ${op ?? ""}` : " "}</div>
        <div className="truncate font-mono text-[clamp(20px,4vw,30px)] font-medium text-textmid">{current}</div>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-4 grid-rows-5 gap-1.5">
        <Key label="AC" kind="fn" onClick={clearAll} />
        <Key label="⌫" kind="fn" onClick={backspace} />
        <Key label="%" kind="fn" onClick={percent} />
        <Key label="÷" kind="op" onClick={() => chooseOp("÷")} />
        {["7", "8", "9"].map((d) => <Key key={d} label={d} onClick={() => inputDigit(d)} />)}
        <Key label="×" kind="op" onClick={() => chooseOp("×")} />
        {["4", "5", "6"].map((d) => <Key key={d} label={d} onClick={() => inputDigit(d)} />)}
        <Key label="−" kind="op" onClick={() => chooseOp("−")} />
        {["1", "2", "3"].map((d) => <Key key={d} label={d} onClick={() => inputDigit(d)} />)}
        <Key label="+" kind="op" onClick={() => chooseOp("+")} />
        <Key label="±" onClick={negate} />
        <Key label="0" onClick={() => inputDigit("0")} />
        <Key label="." onClick={inputDot} />
        <Key label="=" kind="eq" onClick={equals} />
      </div>
    </div>
  );
}

function CalendarBody({ state }: { state: AlgoState }) {
  const map: Record<string, { pnl: number; trades: number }> = {};
  for (const d of state.daily_history ?? []) map[d.date] = { pnl: d.pnl, trades: d.trades };
  const [cursor, setCursor] = useState(() => { const n = new Date(); return { y: n.getFullYear(), m: n.getMonth() }; });
  const todayKey = new Date().toISOString().slice(0, 10);

  const first = new Date(cursor.y, cursor.m, 1);
  const startDow = (first.getDay() + 6) % 7; // Monday-first
  const days = new Date(cursor.y, cursor.m + 1, 0).getDate();
  const cells: (number | null)[] = [...Array(startDow).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)];
  const monthName = first.toLocaleString(undefined, { month: "long", year: "numeric" });
  const key = (d: number) => `${cursor.y}-${String(cursor.m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  const monthPnl = Object.entries(map).filter(([k]) => k.startsWith(`${cursor.y}-${String(cursor.m + 1).padStart(2, "0")}`)).reduce((s, [, v]) => s + v.pnl, 0);
  const shift = (n: number) => setCursor((c) => { const d = new Date(c.y, c.m + n, 1); return { y: d.getFullYear(), m: d.getMonth() }; });

  return (
    <div className="flex h-full flex-col p-3">
      <div className="mb-2 flex items-center justify-between">
        <button onClick={() => shift(-1)} className="px-2 font-mono text-textdim hover:text-gold">‹</button>
        <span className="font-mono text-[12px] uppercase tracking-wider text-gold">{monthName}</span>
        <button onClick={() => shift(1)} className="px-2 font-mono text-textdim hover:text-gold">›</button>
      </div>
      <div className="mb-1 grid grid-cols-7 gap-1 font-mono text-[9px] uppercase text-textdim">
        {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => <div key={i} className="text-center">{d}</div>)}
      </div>
      <div className="grid flex-1 grid-cols-7 gap-1">
        {cells.map((d, i) => {
          if (d == null) return <div key={i} />;
          const k = key(d);
          const rec = map[k];
          const tone = !rec ? "" : rec.pnl >= 0 ? "bg-up/15 border-up/40 text-up" : "bg-down/15 border-down/40 text-down";
          return (
            <div key={i} className={`flex flex-col rounded border p-1 text-[9px] ${rec ? tone : "border-border/40 text-textdim"} ${k === todayKey ? "ring-1 ring-gold" : ""}`} title={rec ? `${rec.trades} trade(s)` : ""}>
              <span className="font-mono">{d}</span>
              {rec && <span className="mt-auto font-bold">{rec.pnl >= 0 ? "+" : ""}{Math.round(rec.pnl)}</span>}
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex justify-between border-t border-border pt-2 font-mono text-[11px]">
        <span className="text-textdim uppercase tracking-wider">Month P&L</span>
        <span className={`font-bold ${monthPnl >= 0 ? "text-up" : "text-down"}`}>{monthPnl >= 0 ? "+" : ""}£{monthPnl.toFixed(2)}</span>
      </div>
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
  { id: "calendar", code: "CDR", name: "P&L Calendar", category: "JOURNAL", w: 7, h: 11, minW: 5, minH: 8, render: (s) => <CalendarBody state={s} /> },
  { id: "calculator", code: "CAL", name: "Calculator", category: "TOOLS", w: 4, h: 12, minW: 3, minH: 9, render: () => <CalculatorBody /> },
  { id: "risk", code: "RSK", name: "Risk / Breakers", category: "RISK", w: 5, h: 7, minW: 3, minH: 4, render: (s) => <RiskBody state={s} /> },
  { id: "indicators", code: "IND", name: "Indicators", category: "ANALYTICS", w: 7, h: 8, minW: 4, minH: 4, render: (s) => <IndicatorsBody state={s} /> },
  { id: "usage", code: "AIU", name: "AI Usage / Cost", category: "AI", w: 4, h: 9, minW: 3, minH: 5, render: (s) => <UsageCost state={s} /> },
  { id: "log", code: "LOG", name: "System Log", category: "SYSTEM", w: 8, h: 8, minW: 4, minH: 4, render: (s) => <LogBody state={s} /> },
];

export const WIDGETS_BY_ID: Record<string, WidgetDef> = Object.fromEntries(WIDGETS.map((w) => [w.id, w]));

export const WIDGET_CATEGORIES: { name: string; items: WidgetDef[] }[] = (() => {
  const order = ["MARKETS", "ACCOUNT", "JOURNAL", "TOOLS", "RISK", "ANALYTICS", "AI", "SYSTEM"];
  return order.map((name) => ({ name, items: WIDGETS.filter((w) => w.category === name) }));
})();
