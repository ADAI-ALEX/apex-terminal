"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StrategyEditor, type Strategy } from "./StrategyEditor";
import { chartColors } from "@/lib/theme";

type Candle = { time: number; open: number; high: number; low: number; close: number };
type EqPoint = { time: number; equity: number };
type Trade = { direction: string; entry: number; exit: number; stop?: number; pnl: number; ret_pct: number; reason: string; strategy: string; opened: string; closed: string };
type Result = {
  error?: string; pending?: boolean; mode?: string; market?: string; bars?: number; minutes?: number;
  starting_equity?: number; final_equity?: number; total_return_pct?: number; trades?: number;
  win_rate?: number; profit_factor?: number; avg_rr?: number; expectancy_pct?: number;
  max_daily_dd_pct?: number; max_total_dd_pct?: number; strategy_label?: string;
  equity_curve?: EqPoint[]; candles?: Candle[]; trade_log?: Trade[]; monte_carlo?: Record<string, number | string>;
};

const MARKETS = ["US500", "NAS100", "EURUSD", "GBPUSD", "FTSE100", "DAX40"];
const LOCAL_INSTRUMENTS = ["US500", "NAS100", "XAUUSD", "BTCUSD", "ETHUSD", "FTSE100", "EURUSD"]; // local offline data
const LOCAL_MARKETS = new Set(LOCAL_INSTRUMENTS);
const LIVE_TF: [number, string][] = [[5, "5m"], [15, "15m"], [30, "30m"], [60, "1h"]];
const LOCAL_TF: [number, string][] = [[1440, "Daily"], [60, "1h"], [15, "15m"], [5, "5m"]];
const SPEEDS: [number, string][] = [[1, "1×"], [3, "3×"], [8, "8×"], [20, "20×"]];
function tfLabel(minutes?: number): string {
  if (minutes === 1440) return "D1";
  if (minutes === 60) return "1h";
  return `${minutes ?? 0}m`;
}
const PALETTE = ["#c9a84c", "#22c55e", "#3b82f6", "#ef4444", "#a855f7", "#14b8a6", "#f97316", "#ec4899"];

const BUILTIN_BOOK: Strategy = {
  name: "book", label: "Strategy Book (built-in)",
  description: "The live multi-strategy book: EMA-trend, RSI-reversion and ATR-breakout, gated by the regime detector.",
  kind: "builtin", editable: false, code: "",
};

const STARTER = `# name: My Strategy
# description: Describe what this algorithm does
#
# Runs once per bar. Set \`signal\` to "BUY", "SELL", "FLAT" or "HOLD".
# Vars: open, high, low, close, volume, price, fear_and_greed, vix, sentiment, hour
# Fns:  sma(p) ema(p) rsi(p) macd() atr(p) adx(p) bollinger(p,s) highest(p) lowest(p)
#       vwap(p) volume_profile(p) -> (poc,vah,val,lvn,width)  cvd(p)  markov(p)
#       crossover(a,b) crossunder(a,b)

upper, mid, lower = bollinger(20, 2)

if rsi(14) < 30 and close < lower and fear_and_greed < 30:
    signal = "BUY"          # oversold capitulation
elif rsi(14) > 70 and close > upper and fear_and_greed > 75:
    signal = "SELL"         # overbought euphoria
else:
    signal = "HOLD"
`;

/** Strict connectivity check used as a guardrail before any backtest run. */
async function checkOnline(): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.onLine === false) return false;
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 3000);
    await fetch("https://www.google.com/generate_204", { mode: "no-cors", cache: "no-store", signal: ctrl.signal });
    clearTimeout(t);
    return true;
  } catch {
    return false;
  }
}

/** POST a backtest and, in cloud-relay mode, poll until the engine returns a result. */
async function submitBacktest(body: Record<string, unknown>, onStatus?: (s: string) => void): Promise<Result> {
  try {
    const res = await fetch("/api/backtest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = (await res.json()) as Result & { id?: string; queued?: boolean };
    if (data.queued && data.id) {
      onStatus?.("Running on your engine (real data)…");
      const deadline = Date.now() + 120_000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 1500));
        const pj = (await (await fetch(`/api/backtest?id=${data.id}`, { cache: "no-store" })).json()) as Result;
        if (!pj.pending) return pj;
      }
      return { error: "Timed out — is the engine running (start.bat)?" };
    }
    return data;
  } catch {
    return { error: "Request failed." };
  }
}

const KIND_ORDER: Record<string, number> = { builtin: 0, default: 1, custom: 2 };

export function BacktestTab() {
  // Persist the active sub-tab (restored on reload); set in an effect to avoid a
  // hydration mismatch.
  const [mode, setMode] = useState<"single" | "compare">("single");
  useEffect(() => {
    const saved = localStorage.getItem("apex.algoMode");
    if (saved === "single" || saved === "compare") setMode(saved);
  }, []);
  useEffect(() => { try { localStorage.setItem("apex.algoMode", mode); } catch { /* ignore */ } }, [mode]);

  // Strategy library (server list merged with local optimistic drafts/deletes)
  const [serverStrategies, setServerStrategies] = useState<Strategy[]>([]);
  const [localDrafts, setLocalDrafts] = useState<Strategy[]>([]);
  const [deleted, setDeleted] = useState<string[]>([]);
  const [strategyName, setStrategyName] = useState("book");
  const [editor, setEditor] = useState<Strategy | null>(null);

  const strategies = useMemo(() => {
    const map = new Map<string, Strategy>();
    for (const s of serverStrategies) map.set(s.name, s);
    for (const s of localDrafts) map.set(s.name, s);
    for (const d of deleted) map.delete(d);
    if (!map.has("book")) map.set("book", BUILTIN_BOOK);
    return [...map.values()].sort((a, b) => (KIND_ORDER[a.kind] - KIND_ORDER[b.kind]) || a.label.localeCompare(b.label));
  }, [serverStrategies, localDrafts, deleted]);

  const loadStrategies = useCallback(async () => {
    try {
      const res = await fetch("/api/strategies", { cache: "no-store" });
      const data = (await res.json()) as { strategies?: Strategy[] };
      if (Array.isArray(data.strategies)) setServerStrategies(data.strategies);
    } catch { /* falls back to merged/built-in */ }
  }, []);
  useEffect(() => { loadStrategies(); }, [loadStrategies]);

  function onSavedStrategy(s: Strategy) {
    setLocalDrafts((prev) => [...prev.filter((p) => p.name !== s.name), s]);
    setDeleted((prev) => prev.filter((d) => d !== s.name));
    setStrategyName(s.name);
    loadStrategies();
  }
  function onDeleteStrategy(slug: string) {
    setEditor(null);
    setDeleted((prev) => (prev.includes(slug) ? prev : [...prev, slug]));
    setLocalDrafts((prev) => prev.filter((p) => p.name !== slug));
    if (strategyName === slug) setStrategyName("book");
    void fetch("/api/strategies", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "delete", name: slug }) }).catch(() => {});
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex shrink-0 items-center gap-3">
        <div className="flex overflow-hidden rounded border border-border font-mono text-[11px]">
          {(["single", "compare"] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)} className={`px-4 py-1.5 uppercase tracking-wider transition ${mode === m ? "bg-gold/15 text-gold" : "text-textdim hover:text-textmid"}`}>
              {m === "single" ? "Single backtest" : "Compare"}
            </button>
          ))}
        </div>
        <span className="font-mono text-[10px] uppercase tracking-wider text-textdim">
          {mode === "single" ? "Replay one algorithm bar-by-bar" : "Race several algorithms on the same instrument"}
        </span>
      </div>

      {/* Both stay mounted (visibility toggle) so results persist when you switch
          sub-tabs or main tabs — only a full page reset clears them. */}
      <div className="min-h-0 flex-1">
        <div className={mode === "single" ? "h-full" : "hidden"}>
          <SingleBacktest strategies={strategies} strategyName={strategyName} setStrategyName={setStrategyName} setEditor={setEditor} />
        </div>
        <div className={mode === "compare" ? "h-full" : "hidden"}>
          <CompareView strategies={strategies} />
        </div>
      </div>

      {editor && (
        <StrategyEditor
          initial={editor}
          existingNames={strategies.map((s) => s.name)}
          onClose={() => setEditor(null)}
          onSaved={onSavedStrategy}
          onDelete={onDeleteStrategy}
        />
      )}
    </div>
  );
}

// ── Single backtest (replay) ────────────────────────────────────────────
function SingleBacktest({
  strategies, strategyName, setStrategyName, setEditor,
}: {
  strategies: Strategy[]; strategyName: string; setStrategyName: (s: string) => void; setEditor: (s: Strategy | null) => void;
}) {
  const [market, setMarket] = useState("US500");
  const [minutes, setMinutes] = useState(1440);
  const [bars, setBars] = useState(1000);
  const [source, setSource] = useState<"local" | "live">("local");
  const [applyCosts, setApplyCosts] = useState(true);
  const [running, setRunning] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [progress, setProgress] = useState(0);
  const [offlineWarn, setOfflineWarn] = useState("");
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(3);

  const candles = result?.candles ?? [];
  const equity = result?.equity_curve ?? [];
  const trades = result?.trade_log ?? [];
  const startEq = result?.starting_equity ?? 100_000;
  const ready = !!(result && !result.error);
  const hasData = candles.length > 0;

  const selectedStrategy = useMemo(() => strategies.find((s) => s.name === strategyName) ?? null, [strategies, strategyName]);
  useEffect(() => { if (selectedStrategy && selectedStrategy.kind !== "builtin") setSource("local"); }, [selectedStrategy]);
  // Switching data source: keep instrument + timeframe valid for that source.
  useEffect(() => {
    if (source === "live") {
      if (!MARKETS.includes(market)) setMarket("US500");
      if (!LIVE_TF.some(([v]) => v === minutes)) setMinutes(15);
    } else if (!LOCAL_TF.some(([v]) => v === minutes)) {
      setMinutes(1440);
    }
  }, [source, market, minutes]);

  async function run() {
    setOfflineWarn(""); setStatusMsg("Checking connection…");
    if (!(await checkOnline())) {
      setStatusMsg("");
      setOfflineWarn("You appear to be offline. A working internet connection is required to run a backtest right now — reconnect and try again.");
      return;
    }
    setRunning(true); setResult(null); setIdx(0); setPlaying(false); setProgress(8); setStatusMsg("Submitting backtest…");
    const r = await submitBacktest({ market, minutes, bars, target_pct: 10, total_limit_pct: 10, strategy: strategyName, source, apply_costs: applyCosts }, setStatusMsg);
    setProgress(100); setRunning(false); setStatusMsg("");
    setResult(r);
    if (!r.error && (r.candles?.length ?? 0) > 0) { setIdx(0); setPlaying(true); }
  }

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setProgress((p) => Math.min(96, p + (96 - p) * 0.08)), 140);
    return () => clearInterval(id);
  }, [running]);

  useEffect(() => {
    if (!playing || candles.length === 0) return;
    const id = setInterval(() => setIdx((i) => { const next = i + speed; if (next >= candles.length) { setPlaying(false); return candles.length; } return next; }), 80);
    return () => clearInterval(id);
  }, [playing, speed, candles.length]);

  // Time-aware metrics: everything recomputes from the trades/equity revealed up to
  // the current replay bar, so the Performance panel changes, freezes on pause, and
  // rewinds when the scrubber moves.
  const m = useMemo(() => {
    if (!candles.length) return null;
    const cut = candles[Math.max(0, Math.min(idx, candles.length) - 1)]?.time ?? 0;
    const eqShown = equity.filter((p) => p.time <= cut);
    const lastEq = eqShown.length ? eqShown[eqShown.length - 1].equity : startEq;
    let peak = startEq, maxTotalDD = 0;
    const dayStart: Record<string, number> = {}, dayMin: Record<string, number> = {};
    for (const p of eqShown) {
      peak = Math.max(peak, p.equity);
      maxTotalDD = Math.max(maxTotalDD, peak > 0 ? (100 * (peak - p.equity)) / peak : 0);
      const d = new Date(p.time * 1000).toISOString().slice(0, 10);
      if (!(d in dayStart)) dayStart[d] = p.equity;
      dayMin[d] = Math.min(dayMin[d] ?? p.equity, p.equity);
    }
    let maxDailyDD = 0;
    for (const d in dayStart) if (dayStart[d] > 0) maxDailyDD = Math.max(maxDailyDD, (100 * (dayStart[d] - dayMin[d])) / dayStart[d]);
    const done = trades.filter((t) => new Date(t.closed).getTime() / 1000 <= cut);
    let wins = 0, grossWin = 0, grossLoss = 0, rrSum = 0, rrCount = 0, retSum = 0;
    for (const t of done) {
      if (t.pnl >= 0) { wins++; grossWin += t.pnl; } else grossLoss += -t.pnl;
      retSum += t.ret_pct;
      const risk = Math.abs(t.entry - (t.stop ?? t.entry));
      if (risk > 0) { rrSum += Math.abs(t.exit - t.entry) / risk; rrCount++; }
    }
    const n = done.length;
    return {
      bar: Math.min(idx, candles.length), total: candles.length,
      date: cut ? new Date(cut * 1000).toLocaleDateString() : "—",
      equity: lastEq, totalReturn: (100 * (lastEq - startEq)) / startEq,
      maxTotalDD, maxDailyDD, trades: n, winRate: n ? (100 * wins) / n : 0,
      profitFactor: grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? 999 : 0,
      avgRR: rrCount ? rrSum / rrCount : 0, expectancy: n ? retSum / n : 0,
    };
  }, [idx, candles, equity, trades, startEq]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 lg:flex-row">
      {/* CENTER */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
        <div className="shrink-0 rounded-md border border-border bg-bg2 p-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Instrument"><Select value={market} onChange={setMarket} options={(source === "local" ? LOCAL_INSTRUMENTS : MARKETS).map((mk) => [mk, mk])} /></Field>
            <Field label="Data source">
              <div className="flex h-9 overflow-hidden rounded border border-border">
                {(["local", "live"] as const).map((s) => {
                  const disabled = s === "live" && !!selectedStrategy && selectedStrategy.kind !== "builtin";
                  return (
                    <button key={s} onClick={() => !disabled && setSource(s)} disabled={disabled} title={disabled ? "Custom strategies run on local data" : undefined}
                      className={`px-3 text-xs font-bold transition ${source === s ? "bg-gold/15 text-gold" : "text-textdim hover:text-gold"} ${disabled ? "cursor-not-allowed opacity-40" : ""}`}>
                      {s === "local" ? "Local 20y" : "Live"}
                    </button>
                  );
                })}
              </div>
            </Field>
            <Field label="Timeframe"><Select value={String(minutes)} onChange={(v) => setMinutes(Number(v))} options={(source === "local" ? LOCAL_TF : LIVE_TF).map(([v, l]) => [String(v), l])} /></Field>
            <Field label="Bars"><NumberInput value={bars} onChange={setBars} step={source === "local" && minutes === 1440 ? 250 : 100} /></Field>
            <Field label="Costs">
              <button
                onClick={() => setApplyCosts((v) => !v)}
                title="Charge realistic spread + commission per trade (recommended)"
                className={`h-9 rounded px-3 text-sm font-bold ${applyCosts ? "bg-up/20 text-up border border-up/50" : "bg-bg3 text-textmid border border-border"}`}
              >
                {applyCosts ? "✓ On" : "Off"}
              </button>
            </Field>
            <button onClick={run} disabled={running} className="btn-gold h-9 rounded px-6 text-sm font-bold">{running ? "Running…" : "Run backtest"}</button>
            {statusMsg && <span className="font-mono text-xs text-textmid">{statusMsg}</span>}
          </div>
          {running && !hasData && (
            <div className="mt-3 h-1.5 w-full overflow-hidden rounded bg-bg3">
              <div className="fill-gold-grad h-full rounded transition-all duration-150" style={{ width: `${progress}%` }} />
            </div>
          )}
        </div>

        {offlineWarn && (
          <div className="flex shrink-0 items-start gap-2 rounded-md border border-down/50 bg-down/10 px-4 py-2.5 text-sm text-down">
            <span className="text-lg leading-none">⚠</span>
            <div><div className="font-bold">Offline — backtest blocked</div><div className="text-down/90">{offlineWarn}</div></div>
          </div>
        )}
        {result?.error && <div className="shrink-0 rounded-md border border-down/40 bg-down/10 px-4 py-2.5 text-sm text-down">{result.error}</div>}

        {/* CHART */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-border bg-bg2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-border px-3 py-2">
            <span className="font-mono text-[10px] uppercase tracking-wider text-gold">// Price &amp; trades</span>
            {ready && (
              <>
                <span className="font-mono text-[11px] text-textmid">{result!.market} · {tfLabel(result!.minutes)} · {result!.bars} bars</span>
                <span className={`rounded px-2 py-0.5 font-mono text-[10px] ${result!.mode === "PAPER" ? "bg-info/10 text-info" : "bg-up/10 text-up"}`}>
                  {result!.mode === "IG" ? "REAL IG DATA" : result!.mode === "LOCAL" ? "LOCAL 20Y DATA" : result!.mode === "PAPER" ? "SIMULATED" : "DATA"}
                </span>
              </>
            )}
            {hasData && m && (
              <div className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px]">
                <Chip label="bar" value={`${m.bar}/${m.total}`} />
                <Chip label="date" value={m.date} />
                <Chip label="equity" value={`£${m.equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}`} />
                <Chip label="ret" value={`${m.totalReturn >= 0 ? "+" : ""}${m.totalReturn.toFixed(2)}%`} tone={m.totalReturn >= 0 ? "up" : "down"} />
              </div>
            )}
          </div>
          <div className="relative min-h-0 flex-1">
            {hasData
              ? <PriceChart candles={candles} trades={trades} idx={idx} />
              : <div className="flex h-full w-full items-center justify-center px-6 text-center font-mono text-xs text-textdim">{running ? "Running backtest…" : "Pick a strategy and instrument, then Run backtest. The replay animates bar-by-bar here."}</div>}
          </div>
          {hasData && (
            <div className="flex flex-wrap items-center gap-2 border-t border-border px-3 py-2">
              <button onClick={() => { if (idx >= candles.length) setIdx(0); setPlaying((p) => !p); }} className="btn-gold h-7 rounded px-3 text-xs font-bold">
                {playing ? "⏸ Pause" : idx >= candles.length ? "↻ Replay" : "▶ Play"}
              </button>
              <div className="flex overflow-hidden rounded border border-border font-mono text-[10px]">
                {SPEEDS.map(([v, l]) => (<button key={v} onClick={() => setSpeed(v)} className={`px-2 py-1 ${speed === v ? "bg-gold/15 text-gold" : "text-textdim hover:text-gold"}`}>{l}</button>))}
              </div>
              <input type="range" min={0} max={candles.length} value={idx} onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }} className="range-gold h-1.5 flex-1" />
            </div>
          )}
        </div>

        {/* METRICS — track the replay time */}
        <div className="shrink-0 rounded-md border border-border bg-bg2 p-3">
          <div className="mb-2 flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-wider text-gold">// Performance</span>
            {hasData && m && <span className="font-mono text-[10px] text-textdim">@ {m.date} · bar {m.bar}/{m.total}</span>}
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
            <Stat label="Total return" value={m ? pct1(m.totalReturn) : "—"} tone={m ? (m.totalReturn >= 0 ? "up" : "down") : undefined} />
            <Stat label="Trades" value={m ? String(m.trades) : "—"} />
            <Stat label="Win rate" value={m ? `${m.winRate.toFixed(0)}%` : "—"} />
            <Stat label="Profit factor" value={m ? (m.profitFactor >= 999 ? "∞" : m.profitFactor.toFixed(2)) : "—"} />
            <Stat label="Avg R:R" value={m ? m.avgRR.toFixed(2) : "—"} />
            <Stat label="Expectancy" value={m ? pct2(m.expectancy) : "—"} />
            <Stat label="Max daily DD" value={m ? `${m.maxDailyDD.toFixed(2)}%` : "—"} tone={m ? "down" : undefined} />
            <Stat label="Max total DD" value={m ? `${m.maxTotalDD.toFixed(2)}%` : "—"} tone={m ? "down" : undefined} />
          </div>
          {ready && result!.monte_carlo && Number(result!.monte_carlo.runs ?? 0) > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border pt-2 font-mono text-[11px]">
              <span className="text-[10px] uppercase tracking-wider text-textdim">Monte Carlo ({result!.monte_carlo!.runs} runs)</span>
              <span className="text-up">P(pass) {result!.monte_carlo!.pass_prob_pct}%</span>
              <span className="text-down">P(breach) {result!.monte_carlo!.breach_prob_pct}%</span>
              <span className="text-textmid">median {result!.monte_carlo!.median_return_pct}%</span>
              <span className="text-textdim">P5 {result!.monte_carlo!.p5_return_pct}% · P95 {result!.monte_carlo!.p95_return_pct}%</span>
            </div>
          )}
        </div>
      </div>

      {/* RIGHT */}
      <aside className="flex w-full shrink-0 flex-col gap-3 lg:w-72">
        <div className="shrink-0 rounded-md border border-border bg-bg2 p-3">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-gold">// Algorithm</div>
          <Select value={strategyName} onChange={setStrategyName} options={strategies.map((s) => [s.name, s.label])} full />
          <div className="mt-2 flex gap-2">
            <button onClick={() => setEditor({ name: "", label: "", description: "", kind: "custom", editable: true, code: STARTER })}
              className="flex h-9 flex-1 items-center justify-center gap-1.5 rounded border border-gold/50 bg-gold/10 text-xs font-bold text-gold transition hover:bg-gold/20">
              <span className="text-base leading-none">+</span> Create Custom Strategy
            </button>
            {selectedStrategy?.editable && (
              <button onClick={() => setEditor(selectedStrategy)} className="h-9 rounded border border-border bg-bg3 px-3 text-xs font-bold text-textmid transition hover:text-gold">Edit</button>
            )}
          </div>
          {selectedStrategy?.description && <p className="mt-3 text-[11px] leading-snug text-textdim">{selectedStrategy.description}</p>}
          {selectedStrategy && selectedStrategy.kind !== "builtin" && (
            <div className="mt-2 inline-flex items-center gap-1 rounded bg-gold/10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider text-gold">{selectedStrategy.kind} strategy</div>
          )}
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-border bg-bg2">
          <div className="border-b border-border px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-gold">// Equity curve</div>
          <div className="relative min-h-[140px] flex-1">
            {hasData
              ? <EquityChart equity={equity} candles={candles} idx={idx} startEq={startEq} />
              : <div className="flex h-full items-center justify-center px-4 text-center font-mono text-[11px] text-textdim">Equity grows here as the replay runs.</div>}
          </div>
          {source === "local" && <div className="border-t border-border px-3 py-2 font-mono text-[9px] leading-snug text-textdim">Offline {tfLabel(minutes)} · US500/NAS100/XAUUSD/BTC/ETH/FTSE100/EURUSD · clean data + costs. Algorithm sets its own risk %.</div>}
        </div>
      </aside>
    </div>
  );
}

// ── Compare view ────────────────────────────────────────────────────────
type CompareSeries = { name: string; label: string; color: string; points: { time: number; value: number }[]; finalPct: number; trades: number; error?: string };
type CompareRun = { candles: Candle[]; series: CompareSeries[] };

function CompareView({ strategies }: { strategies: Strategy[] }) {
  const [market, setMarket] = useState("US500");
  const [minutes, setMinutes] = useState(1440);
  const [bars, setBars] = useState(1000);
  const [selected, setSelected] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState("");
  const [offlineWarn, setOfflineWarn] = useState("");
  const [run, setRun] = useState<CompareRun | null>(null);
  const [showPrice, setShowPrice] = useState(false);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(8);
  const initialized = useRef(false);

  // Seed the selection once (book + any custom/default strategies, capped). A ref
  // guard means clearing all selections never re-seeds them.
  useEffect(() => {
    if (initialized.current || !strategies.length) return;
    initialized.current = true;
    setSelected(["book", ...strategies.filter((s) => s.kind !== "builtin").map((s) => s.name)].slice(0, 6));
  }, [strategies]);

  function toggle(name: string) {
    setSelected((prev) => (prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]));
  }

  // Run every selected strategy (sequentially — they share the backtest relay),
  // collect candles + each equity curve, THEN replay them together so the curves
  // animate in lock-step rather than popping in one-by-one.
  async function doRun() {
    setOfflineWarn("");
    if (!(await checkOnline())) { setOfflineWarn("You appear to be offline. A working internet connection is required to run a comparison."); return; }
    if (!selected.length) return;
    setRunning(true); setRun(null); setPlaying(false); setIdx(0);
    const out: CompareSeries[] = [];
    let candles: Candle[] = [];
    let i = 0;
    for (const name of selected) {
      const meta = strategies.find((s) => s.name === name);
      const label = meta?.label ?? name;
      setStatus(`Running ${label} (${i + 1}/${selected.length})…`);
      const r = await submitBacktest({ market, minutes, bars, target_pct: 10, total_limit_pct: 10, strategy: name, source: "local" });
      const color = PALETTE[i % PALETTE.length];
      if (r.error || !r.equity_curve?.length) {
        out.push({ name, label, color, points: [], finalPct: 0, trades: 0, error: r.error ?? "no data" });
      } else {
        if (!candles.length && r.candles?.length) candles = r.candles;
        const startEq = r.starting_equity ?? 100_000;
        const points = r.equity_curve.map((p) => ({ time: p.time, value: (100 * (p.equity - startEq)) / startEq }));
        out.push({ name, label, color, points, finalPct: points[points.length - 1]?.value ?? 0, trades: r.trades ?? 0 });
      }
      i++;
    }
    setRunning(false); setStatus("");
    setRun({ candles, series: out });
    if (candles.length) { setIdx(0); setPlaying(true); }
  }

  const candles = run?.candles ?? [];
  const drawSeries = useMemo(() => (run?.series ?? []).filter((s) => s.points.length), [run]);
  const hasData = candles.length > 0 && drawSeries.length > 0;

  // Replay ticker (shared cadence with the single backtest).
  useEffect(() => {
    if (!playing || candles.length === 0) return;
    const id = setInterval(() => setIdx((j) => { const next = j + speed; if (next >= candles.length) { setPlaying(false); return candles.length; } return next; }), 80);
    return () => clearInterval(id);
  }, [playing, speed, candles.length]);

  // Leaderboard reflects each algorithm's value at the current replay bar.
  const ranked = useMemo(() => {
    if (!run) return [];
    const cut = candles[Math.max(0, Math.min(idx, candles.length) - 1)]?.time ?? Infinity;
    return run.series.map((s) => {
      let cur = 0;
      for (const p of s.points) { if (p.time <= cut) cur = p.value; else break; }
      return { ...s, cur };
    }).sort((a, b) => b.cur - a.cur);
  }, [run, idx, candles]);

  const replayDate = candles[Math.max(0, Math.min(idx, candles.length) - 1)]?.time;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 lg:flex-row">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
        <div className="shrink-0 rounded-md border border-border bg-bg2 p-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Instrument"><Select value={market} onChange={setMarket} options={[...LOCAL_MARKETS].map((mk) => [mk, mk])} /></Field>
            <Field label="Timeframe"><Select value={String(minutes)} onChange={(v) => setMinutes(Number(v))} options={LOCAL_TF.map(([v, l]) => [String(v), l])} /></Field>
            <Field label="Bars"><NumberInput value={bars} onChange={setBars} step={minutes === 1440 ? 250 : 100} /></Field>
            <button onClick={doRun} disabled={running || !selected.length} className="btn-gold h-9 rounded px-6 text-sm font-bold">{running ? "Running…" : "Run comparison"}</button>
            {status && <span className="font-mono text-xs text-textmid">{status}</span>}
          </div>
          {offlineWarn && <div className="mt-2 rounded border border-down/50 bg-down/10 px-3 py-2 text-xs text-down">⚠ {offlineWarn}</div>}
          <div className="mt-1 font-mono text-[10px] text-textdim">Offline · {tfLabel(minutes)} bars · equity normalised to % return from start. Algorithms set their own risk.</div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-border bg-bg2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-3 py-2">
            <span className="font-mono text-[10px] uppercase tracking-wider text-gold">// Equity race — {market}</span>
            {hasData && replayDate && <span className="font-mono text-[10px] text-textdim">@ {new Date(replayDate * 1000).toLocaleDateString()}</span>}
            {/* top-right: toggle the instrument's live price candles on/off */}
            <label className="ml-auto flex cursor-pointer select-none items-center gap-1.5 font-mono text-[10px] text-textmid">
              <input type="checkbox" checked={showPrice} onChange={(e) => setShowPrice(e.target.checked)} className="range-gold h-3 w-3" />
              Show price
            </label>
          </div>
          <div className="relative min-h-0 flex-1">
            {hasData
              ? <CompareReplayChart candles={candles} series={drawSeries} idx={idx} showPrice={showPrice} />
              : <div className="flex h-full items-center justify-center px-6 text-center font-mono text-xs text-textdim">{running ? "Running each algorithm…" : "Select algorithms on the right, then Run comparison to race their equity curves on a live replay."}</div>}
          </div>
          {hasData && (
            <div className="flex flex-wrap items-center gap-2 border-t border-border px-3 py-2">
              <button onClick={() => { if (idx >= candles.length) setIdx(0); setPlaying((p) => !p); }} className="btn-gold h-7 rounded px-3 text-xs font-bold">
                {playing ? "⏸ Pause" : idx >= candles.length ? "↻ Replay" : "▶ Play"}
              </button>
              <div className="flex overflow-hidden rounded border border-border font-mono text-[10px]">
                {SPEEDS.map(([v, l]) => (<button key={v} onClick={() => setSpeed(v)} className={`px-2 py-1 ${speed === v ? "bg-gold/15 text-gold" : "text-textdim hover:text-gold"}`}>{l}</button>))}
              </div>
              <input type="range" min={0} max={candles.length} value={idx} onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }} className="range-gold h-1.5 flex-1" />
              <span className="font-mono text-[11px] text-textdim">bar {Math.min(idx, candles.length)}/{candles.length}</span>
            </div>
          )}
        </div>
      </div>

      {/* RIGHT: selection + live leaderboard */}
      <aside className="flex w-full shrink-0 flex-col gap-3 lg:w-72">
        <div className="shrink-0 rounded-md border border-border bg-bg2 p-3">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-gold">// Algorithms ({selected.length})</div>
          <div className="max-h-56 space-y-1 overflow-y-auto">
            {strategies.map((s) => {
              const on = selected.includes(s.name);
              return (
                <button key={s.name} onClick={() => toggle(s.name)} className={`flex w-full items-center gap-2 rounded border px-2 py-1.5 text-left text-xs transition ${on ? "border-gold/50 bg-gold/10" : "border-border bg-bg3 hover:border-gold/40"}`}>
                  <span className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm border ${on ? "border-gold bg-gold/30" : "border-textdim"}`}>{on && <span className="text-[9px] text-gold">✓</span>}</span>
                  <span className={`truncate ${on ? "text-gold" : "text-textmid"}`}>{s.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-border bg-bg2">
          <div className="border-b border-border px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-gold">// Leaderboard</div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {ranked.length === 0
              ? <div className="px-2 py-4 text-center font-mono text-[11px] text-textdim">Run a comparison to race algorithms by return.</div>
              : ranked.map((s, i) => (
                <div key={s.name} className="flex items-center gap-2 rounded px-2 py-1.5">
                  <span className="w-4 font-mono text-[11px] text-textdim">{i + 1}</span>
                  <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: s.color }} />
                  <span className="min-w-0 flex-1 truncate text-[12px] text-textmid">{s.label}</span>
                  {s.error
                    ? <span className="font-mono text-[10px] text-down">err</span>
                    : <span className={`font-mono text-[12px] font-bold ${s.cur >= 0 ? "text-up" : "text-down"}`}>{s.cur >= 0 ? "+" : ""}{s.cur.toFixed(1)}%</span>}
                </div>
              ))}
          </div>
        </div>
      </aside>
    </div>
  );
}

/** Synchronised replay: instrument price candles (right scale, toggleable) +
    every algorithm's equity curve (left scale, % return), revealed up to `idx`,
    with a live bubble at the tip of each curve. */
function CompareReplayChart({ candles, series, idx, showPrice }: { candles: Candle[]; series: CompareSeries[]; idx: number; showPrice: boolean }) {
  const elRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const candleRef = useRef<any>(null);
  const tsRef = useRef<any>(null);
  const linesRef = useRef<{ ls: any; s: CompareSeries; pts: { time: number; value: number }[] }[]>([]);
  const cutRef = useRef<number>(0);
  const placeRef = useRef<() => void>(() => {});
  const drawRef = useRef<() => void>(() => {});
  const viewRef = useRef({ idx, showPrice });
  const cleanupRef = useRef<(() => void) | null>(null);
  const [labels, setLabels] = useState<{ x: number; y: number; text: string; up: boolean; color: string }[]>([]);

  // (Re)build the chart whenever the run data changes.
  useEffect(() => {
    let disposed = false;
    let ro: ResizeObserver | null = null;
    (async () => {
      const lib = await import("lightweight-charts");
      const c = chartColors();
      if (disposed || !elRef.current) return;
      const ch = lib.createChart(elRef.current, {
        layout: { background: { color: c.bg }, textColor: c.text },
        grid: { vertLines: { color: "transparent" }, horzLines: { color: c.grid } },
        timeScale: { timeVisible: false, borderColor: c.border },
        rightPriceScale: { borderColor: c.border, visible: true },
        leftPriceScale: { borderColor: c.border, visible: true, scaleMargins: { top: 0.12, bottom: 0.08 } },
        autoSize: true,
      } as any);
      chartRef.current = ch; tsRef.current = ch.timeScale();
      candleRef.current = ch.addCandlestickSeries({ priceScaleId: "right", upColor: "#22c55e", downColor: "#ef4444", borderVisible: false, wickUpColor: "#22c55e", wickDownColor: "#ef4444" });
      linesRef.current = series.map((s) => {
        const ls = ch.addLineSeries({ priceScaleId: "left", color: s.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
        const seen = new Set<number>();
        const pts = [...s.points].sort((a, b) => a.time - b.time).filter((p) => (seen.has(p.time) ? false : (seen.add(p.time), true)));
        return { ls, s, pts };
      });

      placeRef.current = () => {
        if (disposed || !tsRef.current) return;
        const ts = tsRef.current, cut = cutRef.current;
        const next = linesRef.current.map(({ ls, s, pts }) => {
          let last: { time: number; value: number } | null = null;
          for (const p of pts) { if (p.time <= cut) last = p; else break; }
          if (!last) return null;
          const x = ts.timeToCoordinate(last.time as any);
          const y = ls.priceToCoordinate(last.value);
          if (x == null || y == null) return null;
          return { x: x as number, y: y as number, text: `${s.label}  ${last.value >= 0 ? "+" : ""}${last.value.toFixed(1)}%`, up: last.value >= 0, color: s.color };
        }).filter(Boolean) as { x: number; y: number; text: string; up: boolean; color: string }[];
        setLabels(next);
      };

      drawRef.current = () => {
        if (disposed || !candleRef.current) return;
        const { idx: vi, showPrice: sp } = viewRef.current;
        const cut = candles[Math.max(0, Math.min(vi, candles.length) - 1)]?.time ?? 0;
        cutRef.current = cut;
        candleRef.current.applyOptions({ visible: sp });
        try { ch.priceScale("right").applyOptions({ visible: sp }); } catch {}
        if (sp) {
          const seen = new Set<number>();
          const shown = [...candles.slice(0, Math.max(1, vi))].sort((a, b) => a.time - b.time).filter((r) => (seen.has(r.time) ? false : (seen.add(r.time), true)));
          candleRef.current.setData(shown);
        }
        for (const { ls, pts } of linesRef.current) ls.setData(pts.filter((p) => p.time <= cut));
        placeRef.current();
      };

      const sub = () => placeRef.current();
      ch.timeScale().subscribeVisibleTimeRangeChange(sub);
      ro = new ResizeObserver(() => placeRef.current());
      ro.observe(elRef.current);
      cleanupRef.current = () => { try { ch.timeScale().unsubscribeVisibleTimeRangeChange(sub); } catch {} ro?.disconnect(); };
      drawRef.current(); // initial paint
    })();
    return () => { disposed = true; cleanupRef.current?.(); cleanupRef.current = null; chartRef.current?.remove(); chartRef.current = candleRef.current = tsRef.current = null; linesRef.current = []; };
  }, [candles, series]);

  // Reveal up to the current bar / toggle price without rebuilding the chart.
  useEffect(() => { viewRef.current = { idx, showPrice }; drawRef.current(); }, [idx, showPrice]);

  return (
    <div className="absolute inset-0">
      <div ref={elRef} className="absolute inset-0" />
      {labels.map((l, i) => (
        <div
          key={i}
          style={{ left: l.x - 6, top: l.y, borderColor: l.color, transform: "translate(-100%, -50%)" }}
          className={`pointer-events-none absolute z-10 max-w-[55%] truncate rounded-full border bg-bg2/95 px-2 py-0.5 font-mono text-[10px] font-bold shadow ${l.up ? "text-up" : "text-down"}`}
        >
          {l.text}
        </div>
      ))}
    </div>
  );
}

// ── helpers ─────────────────────────────────────────────────────────────
function pct1(v: number) { return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`; }
function pct2(v: number) { return `${v >= 0 ? "+" : ""}${v.toFixed(3)}%`; }
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><div className="mb-1 font-mono text-[9px] uppercase tracking-wider text-textdim">{label}</div>{children}</div>;
}
function Select({ value, onChange, options, full }: { value: string; onChange: (v: string) => void; options: [string, string][]; full?: boolean }) {
  return <select value={value} onChange={(e) => onChange(e.target.value)} className={`h-9 rounded border border-border bg-bg3 px-3 text-sm outline-none focus:border-gold ${full ? "w-full" : ""}`}>{options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>;
}
function NumberInput({ value, onChange, step }: { value: number; onChange: (v: number) => void; step: number }) {
  return <input type="number" step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="h-9 w-24 rounded border border-border bg-bg3 px-3 text-sm outline-none focus:border-gold" />;
}
function Stat({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  return <div className="rounded border border-border bg-bg3 px-3 py-2"><div className="font-mono text-[9px] uppercase tracking-wider text-textdim">{label}</div><div className={`mt-0.5 text-base font-bold ${tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-gold"}`}>{value}</div></div>;
}
function Chip({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  return <span className="flex items-center gap-1"><span className="text-textdim">{label}</span><span className={tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-textmid"}>{value}</span></span>;
}

/** Hero candlestick chart with trade markers, revealed up to `idx`. */
function PriceChart({ candles, trades, idx }: { candles: Candle[]; trades: Trade[]; idx: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<any>(null);
  const series = useRef<any>(null);
  useEffect(() => {
    let disposed = false;
    (async () => {
      const lib = await import("lightweight-charts");
      const c = chartColors();
      if (disposed || !ref.current) return;
      const ch = lib.createChart(ref.current, {
        layout: { background: { color: c.bg }, textColor: c.text },
        grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
        timeScale: { timeVisible: true, borderColor: c.border },
        rightPriceScale: { borderColor: c.border }, autoSize: true,
      } as any);
      series.current = ch.addCandlestickSeries({ upColor: "#22c55e", downColor: "#ef4444", borderVisible: false, wickUpColor: "#22c55e", wickDownColor: "#ef4444" });
      chart.current = ch;
    })();
    return () => { disposed = true; chart.current?.remove(); chart.current = series.current = null; };
  }, []);
  useEffect(() => {
    const s = series.current;
    if (!s) return;
    const seen = new Set<number>();
    const shown = [...candles.slice(0, Math.max(1, idx))].sort((a, b) => a.time - b.time).filter((r) => (seen.has(r.time) ? false : (seen.add(r.time), true)));
    s.setData(shown);
    const cut = shown.length ? shown[shown.length - 1].time : 0;
    const markers = trades.filter((t) => new Date(t.closed).getTime() / 1000 <= cut)
      .map((t) => ({ time: Math.floor(new Date(t.closed).getTime() / 1000), position: t.pnl >= 0 ? "belowBar" : "aboveBar", color: t.pnl >= 0 ? "#22c55e" : "#ef4444", shape: t.pnl >= 0 ? "arrowUp" : "arrowDown", text: `${t.pnl >= 0 ? "+" : ""}${t.pnl}` }));
    try { s.setMarkers(markers as any); } catch {}
  }, [idx, candles, trades]);
  return <div ref={ref} className="absolute inset-0" />;
}

/** Compact equity area chart, revealed up to the same `idx` cut time. */
function EquityChart({ equity, candles, idx, startEq }: { equity: EqPoint[]; candles: Candle[]; idx: number; startEq: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<any>(null);
  const series = useRef<any>(null);
  useEffect(() => {
    let disposed = false;
    (async () => {
      const lib = await import("lightweight-charts");
      const c = chartColors();
      if (disposed || !ref.current) return;
      const ch = lib.createChart(ref.current, {
        layout: { background: { color: c.bg }, textColor: c.text },
        grid: { vertLines: { color: "transparent" }, horzLines: { color: c.grid } },
        timeScale: { timeVisible: false, borderColor: c.border },
        rightPriceScale: { borderColor: c.border }, autoSize: true,
      } as any);
      series.current = ch.addAreaSeries({ lineColor: "#c9a84c", topColor: "rgba(201,168,76,0.25)", bottomColor: "rgba(201,168,76,0.02)", lineWidth: 2 });
      chart.current = ch;
    })();
    return () => { disposed = true; chart.current?.remove(); chart.current = series.current = null; };
  }, []);
  useEffect(() => {
    const s = series.current;
    if (!s) return;
    const cut = candles[Math.max(0, Math.min(idx, candles.length) - 1)]?.time ?? 0;
    const seen = new Set<number>();
    const pts = [...equity.filter((p) => p.time <= cut)].sort((a, b) => a.time - b.time).filter((p) => (seen.has(p.time) ? false : (seen.add(p.time), true))).map((p) => ({ time: p.time, value: p.equity }));
    s.setData(pts.length ? pts : [{ time: Math.floor(Date.now() / 1000), value: startEq }]);
  }, [idx, equity, candles, startEq]);
  return <div ref={ref} className="absolute inset-0" />;
}
