"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StrategyEditor, type Strategy } from "./StrategyEditor";
import { chartColors } from "@/lib/theme";

type Candle = { time: number; open: number; high: number; low: number; close: number };
type EqPoint = { time: number; equity: number };
type Trade = { direction: string; entry: number; exit: number; pnl: number; ret_pct: number; reason: string; strategy: string; opened: string; closed: string };
type Result = {
  error?: string; pending?: boolean; mode?: string; market?: string; bars?: number; minutes?: number;
  starting_equity?: number; final_equity?: number; total_return_pct?: number; trades?: number;
  win_rate?: number; profit_factor?: number; avg_rr?: number; expectancy_pct?: number;
  max_daily_dd_pct?: number; max_total_dd_pct?: number; strategy_label?: string;
  equity_curve?: EqPoint[]; candles?: Candle[]; trade_log?: Trade[]; monte_carlo?: Record<string, number | string>;
};

const MARKETS = ["US500", "NAS100", "EURUSD", "GBPUSD", "FTSE100", "DAX40"];
const LOCAL_MARKETS = new Set(["US500", "FTSE100", "EURUSD"]); // have 20y offline data
const TIMEFRAMES: [number, string][] = [[5, "5m"], [15, "15m"], [30, "30m"], [60, "1h"]];
const SPEEDS: [number, string][] = [[1, "1×"], [3, "3×"], [8, "8×"], [20, "20×"]];

const BUILTIN_BOOK: Strategy = {
  name: "book", label: "Strategy Book (built-in)",
  description: "The live multi-strategy book: EMA-trend, RSI-reversion and ATR-breakout, gated by the regime detector.",
  kind: "builtin", editable: false, code: "",
};

const STARTER = `# name: My Strategy
# description: Describe what this algorithm does
#
# Runs once per bar. Set \`signal\` to "BUY", "SELL", "FLAT" or "HOLD".
# Vars: open, high, low, close, volume, price, fear_and_greed, vix, sentiment
# Fns:  sma(p) ema(p) rsi(p) macd() atr(p) adx(p) bollinger(p,s) highest(p) lowest(p)
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

const KIND_ORDER: Record<string, number> = { builtin: 0, default: 1, custom: 2 };

export function BacktestTab() {
  const [market, setMarket] = useState("US500");
  const [minutes, setMinutes] = useState(15);
  const [bars, setBars] = useState(1500);
  const [riskPct, setRiskPct] = useState(0.4);
  const [running, setRunning] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [progress, setProgress] = useState(0);
  const [offlineWarn, setOfflineWarn] = useState("");

  // Strategy library (server list merged with local optimistic drafts/deletes)
  const [serverStrategies, setServerStrategies] = useState<Strategy[]>([]);
  const [localDrafts, setLocalDrafts] = useState<Strategy[]>([]);
  const [deleted, setDeleted] = useState<string[]>([]);
  const [strategyName, setStrategyName] = useState("book");
  const [source, setSource] = useState<"local" | "live">("local");
  const [editor, setEditor] = useState<Strategy | null>(null);

  // Replay state
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(3);

  const candles = result?.candles ?? [];
  const equity = result?.equity_curve ?? [];
  const trades = result?.trade_log ?? [];
  const startEq = result?.starting_equity ?? 100_000;
  const ready = !!(result && !result.error);

  // Merge server + local so a just-saved strategy shows instantly and a just-deleted
  // one disappears instantly — independent of relay lag.
  const strategies = useMemo(() => {
    const map = new Map<string, Strategy>();
    for (const s of serverStrategies) map.set(s.name, s);
    for (const s of localDrafts) map.set(s.name, s);
    for (const d of deleted) map.delete(d);
    if (!map.has("book")) map.set("book", BUILTIN_BOOK);
    return [...map.values()].sort((a, b) =>
      (KIND_ORDER[a.kind] - KIND_ORDER[b.kind]) || a.label.localeCompare(b.label));
  }, [serverStrategies, localDrafts, deleted]);

  const selectedStrategy = useMemo(
    () => strategies.find((s) => s.name === strategyName) ?? null,
    [strategies, strategyName],
  );

  const loadStrategies = useCallback(async () => {
    try {
      const res = await fetch("/api/strategies", { cache: "no-store" });
      const data = (await res.json()) as { strategies?: Strategy[] };
      if (Array.isArray(data.strategies)) setServerStrategies(data.strategies);
    } catch { /* dropdown falls back to merged/built-in */ }
  }, []);

  useEffect(() => { loadStrategies(); }, [loadStrategies]);

  // Custom / default strategies only run on the local offline dataset.
  useEffect(() => {
    if (selectedStrategy && selectedStrategy.kind !== "builtin") setSource("local");
  }, [selectedStrategy]);

  function onSavedStrategy(s: Strategy) {
    setLocalDrafts((prev) => [...prev.filter((p) => p.name !== s.name), s]);
    setDeleted((prev) => prev.filter((d) => d !== s.name));
    setStrategyName(s.name);
    loadStrategies();
  }

  // Optimistic delete — update the UI instantly, fire the request in the background.
  function onDeleteStrategy(slug: string) {
    setEditor(null);
    setDeleted((prev) => (prev.includes(slug) ? prev : [...prev, slug]));
    setLocalDrafts((prev) => prev.filter((p) => p.name !== slug));
    if (strategyName === slug) setStrategyName("book");
    void fetch("/api/strategies", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "delete", name: slug }),
    }).catch(() => { /* best-effort; UI already reflects the deletion */ });
  }

  async function run() {
    setOfflineWarn("");
    setStatusMsg("Checking connection…");
    if (!(await checkOnline())) {
      setStatusMsg("");
      setOfflineWarn("You appear to be offline. A working internet connection is required to run a backtest right now — reconnect and try again.");
      return;
    }
    const effMinutes = source === "local" ? 1440 : minutes;
    setRunning(true); setResult(null); setIdx(0); setPlaying(false); setProgress(8);
    setStatusMsg("Submitting backtest…");
    try {
      const res = await fetch("/api/backtest", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          market, minutes: effMinutes, bars, risk_pct: riskPct, target_pct: 10, total_limit_pct: 10,
          strategy: strategyName, source,
        }),
      });
      const data = (await res.json()) as Result & { id?: string; queued?: boolean };
      if (data.queued && data.id) {
        setStatusMsg("Running on your engine (real data)…");
        const deadline = Date.now() + 120_000;
        while (Date.now() < deadline) {
          await new Promise((r) => setTimeout(r, 1500));
          const poll = await fetch(`/api/backtest?id=${data.id}`, { cache: "no-store" });
          const pj = (await poll.json()) as Result;
          if (!pj.pending) return finish(pj);
        }
        setStatusMsg("Timed out — is the engine running (start.bat)?"); setRunning(false); return;
      }
      finish(data);
    } catch { setStatusMsg("Request failed."); setRunning(false); }
  }

  function finish(r: Result) {
    setProgress(100);
    setRunning(false); setStatusMsg("");
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
    const id = setInterval(() => {
      setIdx((i) => {
        const next = i + speed;
        if (next >= candles.length) { setPlaying(false); return candles.length; }
        return next;
      });
    }, 80);
    return () => clearInterval(id);
  }, [playing, speed, candles.length]);

  const live = useMemo(() => {
    if (!candles.length) return null;
    const cut = candles[Math.max(0, Math.min(idx, candles.length) - 1)]?.time ?? 0;
    const eqShown = equity.filter((p) => p.time <= cut);
    const lastEq = eqShown.length ? eqShown[eqShown.length - 1].equity : startEq;
    let peak = startEq, maxDD = 0;
    for (const p of eqShown) { peak = Math.max(peak, p.equity); maxDD = Math.max(maxDD, peak > 0 ? (100 * (peak - p.equity)) / peak : 0); }
    const done = trades.filter((t) => new Date(t.closed).getTime() / 1000 <= cut);
    const wins = done.filter((t) => t.pnl >= 0).length;
    return {
      bar: Math.min(idx, candles.length), total: candles.length,
      date: cut ? new Date(cut * 1000).toLocaleDateString() : "—",
      ret: (100 * (lastEq - startEq)) / startEq, equity: lastEq,
      maxDD, trades: done.length, winRate: done.length ? (100 * wins) / done.length : 0,
    };
  }, [idx, candles, equity, trades, startEq]);

  const hasData = candles.length > 0;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 lg:flex-row">
      {/* ── CENTER: controls · chart · metrics ───────────────────────── */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
        {/* Controls */}
        <div className="shrink-0 rounded-md border border-border bg-bg2 p-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Instrument"><Select value={market} onChange={setMarket} options={MARKETS.map((m) => [m, source === "local" && !LOCAL_MARKETS.has(m) ? `${m} (no local)` : m])} /></Field>
            <Field label="Data source">
              <div className="flex h-9 overflow-hidden rounded border border-border">
                {(["local", "live"] as const).map((s) => {
                  const disabled = s === "live" && !!selectedStrategy && selectedStrategy.kind !== "builtin";
                  return (
                    <button key={s} onClick={() => !disabled && setSource(s)} disabled={disabled}
                      title={disabled ? "Custom strategies run on local data" : undefined}
                      className={`px-3 text-xs font-bold transition ${source === s ? "bg-gold/15 text-gold" : "text-textdim hover:text-gold"} ${disabled ? "cursor-not-allowed opacity-40" : ""}`}
                    >{s === "local" ? "Local 20y" : "Live"}</button>
                  );
                })}
              </div>
            </Field>
            {source === "local"
              ? <Field label="Timeframe"><div className="flex h-9 items-center rounded border border-border bg-bg3/60 px-3 text-sm text-textdim">Daily</div></Field>
              : <Field label="Timeframe"><Select value={String(minutes)} onChange={(v) => setMinutes(Number(v))} options={TIMEFRAMES.map(([v, l]) => [String(v), l])} /></Field>}
            <Field label="Bars"><NumberInput value={bars} onChange={setBars} step={source === "local" ? 250 : 50} /></Field>
            <Field label="Risk %/trade"><NumberInput value={riskPct} onChange={setRiskPct} step={0.1} /></Field>
            <button onClick={run} disabled={running} className="h-9 rounded bg-gold px-6 text-sm font-bold text-bg transition hover:bg-gold2 disabled:opacity-50">
              {running ? "Running…" : "Run backtest"}
            </button>
            {statusMsg && <span className="font-mono text-xs text-textmid">{statusMsg}</span>}
          </div>
          {running && !hasData && (
            <div className="mt-3 h-1.5 w-full overflow-hidden rounded bg-bg3">
              <div className="h-full rounded bg-gradient-to-r from-gold/70 to-gold transition-all duration-150" style={{ width: `${progress}%` }} />
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

        {/* CHART (hero, always on screen) */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-border bg-bg2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-border px-3 py-2">
            <span className="font-mono text-[10px] uppercase tracking-wider text-gold">// Price &amp; trades</span>
            {ready && (
              <>
                <span className="font-mono text-[11px] text-textmid">{result!.market} · {result!.minutes === 1440 ? "D1" : `${result!.minutes}m`} · {result!.bars} bars</span>
                <span className={`rounded px-2 py-0.5 font-mono text-[10px] ${result!.mode === "PAPER" ? "bg-info/10 text-info" : "bg-up/10 text-up"}`}>
                  {result!.mode === "IG" ? "REAL IG DATA" : result!.mode === "LOCAL" ? "LOCAL 20Y DATA" : result!.mode === "PAPER" ? "SIMULATED" : "DATA"}
                </span>
              </>
            )}
            {hasData && live && (
              <div className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px]">
                <Chip label="bar" value={`${live.bar}/${live.total}`} />
                <Chip label="date" value={live.date} />
                <Chip label="equity" value={`£${live.equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}`} />
                <Chip label="ret" value={`${live.ret >= 0 ? "+" : ""}${live.ret.toFixed(2)}%`} tone={live.ret >= 0 ? "up" : "down"} />
                <Chip label="DD" value={`${live.maxDD.toFixed(2)}%`} tone="down" />
              </div>
            )}
          </div>

          <div className="relative min-h-0 flex-1">
            {hasData
              ? <PriceChart candles={candles} trades={trades} idx={idx} />
              : <div className="flex h-full w-full items-center justify-center px-6 text-center font-mono text-xs text-textdim">
                  {running ? "Running backtest…" : "Pick a strategy and instrument, then Run backtest. The replay animates bar-by-bar here."}
                </div>}
          </div>

          {hasData && (
            <div className="flex flex-wrap items-center gap-2 border-t border-border px-3 py-2">
              <button onClick={() => { if (idx >= candles.length) setIdx(0); setPlaying((p) => !p); }} className="h-7 rounded bg-gold px-3 text-xs font-bold text-bg hover:bg-gold2">
                {playing ? "⏸ Pause" : idx >= candles.length ? "↻ Replay" : "▶ Play"}
              </button>
              <div className="flex overflow-hidden rounded border border-border font-mono text-[10px]">
                {SPEEDS.map(([v, l]) => (
                  <button key={v} onClick={() => setSpeed(v)} className={`px-2 py-1 ${speed === v ? "bg-gold/15 text-gold" : "text-textdim hover:text-gold"}`}>{l}</button>
                ))}
              </div>
              <input type="range" min={0} max={candles.length} value={idx} onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }} className="h-1.5 flex-1 accent-gold" />
            </div>
          )}
        </div>

        {/* METRICS (always on screen) */}
        <div className="shrink-0 rounded-md border border-border bg-bg2 p-3">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-gold">// Performance</div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
            <Stat label="Total return" value={ready ? pct(result!.total_return_pct) : "—"} tone={ready ? ((result!.total_return_pct ?? 0) >= 0 ? "up" : "down") : undefined} />
            <Stat label="Trades" value={ready ? String(result!.trades ?? 0) : "—"} />
            <Stat label="Win rate" value={ready ? `${result!.win_rate ?? 0}%` : "—"} />
            <Stat label="Profit factor" value={ready ? String(result!.profit_factor ?? 0) : "—"} />
            <Stat label="Avg R:R" value={ready ? String(result!.avg_rr ?? 0) : "—"} />
            <Stat label="Expectancy" value={ready ? pct(result!.expectancy_pct) : "—"} />
            <Stat label="Max daily DD" value={ready ? `${result!.max_daily_dd_pct ?? 0}%` : "—"} tone={ready ? "down" : undefined} />
            <Stat label="Max total DD" value={ready ? `${result!.max_total_dd_pct ?? 0}%` : "—"} tone={ready ? "down" : undefined} />
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

      {/* ── RIGHT: strategy selection / create / edit ────────────────── */}
      <aside className="flex w-full shrink-0 flex-col gap-3 lg:w-72">
        <div className="shrink-0 rounded-md border border-border bg-bg2 p-3">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-gold">// Algorithm</div>
          <Select value={strategyName} onChange={setStrategyName} options={strategies.map((s) => [s.name, s.label])} full />
          <div className="mt-2 flex gap-2">
            <button
              onClick={() => setEditor({ name: "", label: "", description: "", kind: "custom", editable: true, code: STARTER })}
              className="flex h-9 flex-1 items-center justify-center gap-1.5 rounded border border-gold/50 bg-gold/10 text-xs font-bold text-gold transition hover:bg-gold/20"
            ><span className="text-base leading-none">+</span> Create Custom Strategy</button>
            {selectedStrategy?.editable && (
              <button onClick={() => setEditor(selectedStrategy)} className="h-9 rounded border border-border bg-bg3 px-3 text-xs font-bold text-textmid transition hover:text-gold">Edit</button>
            )}
          </div>
          {selectedStrategy?.description && (
            <p className="mt-3 text-[11px] leading-snug text-textdim">{selectedStrategy.description}</p>
          )}
          {selectedStrategy && selectedStrategy.kind !== "builtin" && (
            <div className="mt-2 inline-flex items-center gap-1 rounded bg-gold/10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider text-gold">
              {selectedStrategy.kind} strategy
            </div>
          )}
        </div>

        {/* Equity curve + run summary fills the rest of the sidebar */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-border bg-bg2">
          <div className="border-b border-border px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-gold">// Equity curve</div>
          <div className="relative min-h-[140px] flex-1">
            {hasData
              ? <EquityChart equity={equity} candles={candles} idx={idx} startEq={startEq} />
              : <div className="flex h-full items-center justify-center px-4 text-center font-mono text-[11px] text-textdim">Equity grows here as the replay runs.</div>}
          </div>
          {source === "local" && (
            <div className="border-t border-border px-3 py-2 font-mono text-[9px] leading-snug text-textdim">
              Offline · daily 2006→2026 · US500/FTSE100/EURUSD · vars: fear&amp;greed, VIX, sentiment.
            </div>
          )}
        </div>
      </aside>

      {editor && (
        <StrategyEditor
          initial={editor}
          onClose={() => setEditor(null)}
          onSaved={onSavedStrategy}
          onDelete={onDeleteStrategy}
        />
      )}
    </div>
  );
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
        rightPriceScale: { borderColor: c.border },
        autoSize: true,
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
    const markers = trades
      .filter((t) => new Date(t.closed).getTime() / 1000 <= cut)
      .map((t) => ({ time: Math.floor(new Date(t.closed).getTime() / 1000), position: t.pnl >= 0 ? "belowBar" : "aboveBar", color: t.pnl >= 0 ? "#22c55e" : "#ef4444", shape: t.pnl >= 0 ? "arrowUp" : "arrowDown", text: `${t.pnl >= 0 ? "+" : ""}${t.pnl}` }));
    try { s.setMarkers(markers as any); } catch { /* ignore */ }
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
        rightPriceScale: { borderColor: c.border },
        autoSize: true,
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
    const pts = [...equity.filter((p) => p.time <= cut)].sort((a, b) => a.time - b.time)
      .filter((p) => (seen.has(p.time) ? false : (seen.add(p.time), true)))
      .map((p) => ({ time: p.time, value: p.equity }));
    s.setData(pts.length ? pts : [{ time: Math.floor(Date.now() / 1000), value: startEq }]);
  }, [idx, equity, candles, startEq]);

  return <div ref={ref} className="absolute inset-0" />;
}

// ── helpers ─────────────────────────────────────────────────────────────
function pct(v?: number) { return `${(v ?? 0) >= 0 ? "+" : ""}${v ?? 0}%`; }
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
