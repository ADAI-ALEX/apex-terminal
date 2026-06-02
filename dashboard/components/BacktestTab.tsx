"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type Candle = { time: number; open: number; high: number; low: number; close: number };
type EqPoint = { time: number; equity: number };
type Trade = { direction: string; entry: number; exit: number; pnl: number; ret_pct: number; reason: string; strategy: string; opened: string; closed: string };
type Result = {
  error?: string; pending?: boolean; mode?: string; market?: string; bars?: number; minutes?: number;
  starting_equity?: number; final_equity?: number; total_return_pct?: number; trades?: number;
  win_rate?: number; profit_factor?: number; avg_rr?: number; expectancy_pct?: number;
  max_daily_dd_pct?: number; max_total_dd_pct?: number;
  equity_curve?: EqPoint[]; candles?: Candle[]; trade_log?: Trade[]; monte_carlo?: Record<string, number | string>;
};

const MARKETS = ["US500", "NAS100", "EURUSD", "GBPUSD", "FTSE100", "DAX40"];
const TIMEFRAMES: [number, string][] = [[5, "5m"], [15, "15m"], [30, "30m"], [60, "1h"]];
const SPEEDS: [number, string][] = [[1, "1×"], [3, "3×"], [8, "8×"], [20, "20×"]];

export function BacktestTab() {
  const [market, setMarket] = useState("US500");
  const [minutes, setMinutes] = useState(15);
  const [bars, setBars] = useState(500);
  const [riskPct, setRiskPct] = useState(0.4);
  const [running, setRunning] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");
  const [result, setResult] = useState<Result | null>(null);

  // Replay state
  const [idx, setIdx] = useState(0);     // candles revealed
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(3);

  const candles = result?.candles ?? [];
  const equity = result?.equity_curve ?? [];
  const trades = result?.trade_log ?? [];
  const startEq = result?.starting_equity ?? 100_000;

  async function run() {
    setRunning(true); setResult(null); setIdx(0); setPlaying(false);
    setStatusMsg("Submitting backtest…");
    try {
      const res = await fetch("/api/backtest", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ market, minutes, bars, risk_pct: riskPct, target_pct: 10, total_limit_pct: 10 }),
      });
      const data = (await res.json()) as Result & { id?: string; queued?: boolean };
      if (data.queued && data.id) {
        setStatusMsg("Running on your engine (real data)…");
        const deadline = Date.now() + 120_000;
        while (Date.now() < deadline) {
          await new Promise((r) => setTimeout(r, 2500));
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
    setRunning(false); setStatusMsg("");
    setResult(r);
    if (!r.error && (r.candles?.length ?? 0) > 0) { setIdx(0); setPlaying(true); }
  }

  // Replay ticker.
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

  // Live metrics up to the current replay point.
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
      date: cut ? new Date(cut * 1000).toLocaleString() : "—",
      ret: (100 * (lastEq - startEq)) / startEq, equity: lastEq,
      maxDD, trades: done.length, winRate: done.length ? (100 * wins) / done.length : 0,
    };
  }, [idx, candles, equity, trades, startEq]);

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="rounded-md border border-border bg-bg2 p-4">
        <div className="mb-3 font-mono text-[10px] uppercase tracking-wider text-gold">// Backtest — replay the strategy book on historical data</div>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Instrument"><Select value={market} onChange={setMarket} options={MARKETS.map((m) => [m, m])} /></Field>
          <Field label="Timeframe"><Select value={String(minutes)} onChange={(v) => setMinutes(Number(v))} options={TIMEFRAMES.map(([v, l]) => [String(v), l])} /></Field>
          <Field label="Bars"><NumberInput value={bars} onChange={setBars} step={50} /></Field>
          <Field label="Risk %/trade"><NumberInput value={riskPct} onChange={setRiskPct} step={0.1} /></Field>
          <button onClick={run} disabled={running} className="rounded bg-gold px-6 py-2 text-sm font-bold text-black transition hover:bg-gold2 disabled:opacity-50">
            {running ? "Running…" : "Run backtest"}
          </button>
          {statusMsg && <span className="font-mono text-xs text-textmid">{statusMsg}</span>}
        </div>
      </div>

      {result?.error && <div className="rounded-md border border-down/40 bg-down/10 px-4 py-3 text-sm text-down">{result.error}</div>}

      {result && !result.error && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-mono text-sm text-textmid">{result.market} · {result.minutes}m · {result.bars} bars</span>
            <span className={`rounded px-2 py-0.5 font-mono text-[10px] ${result.mode === "IG" ? "bg-up/10 text-up" : "bg-info/10 text-info"}`}>
              {result.mode === "IG" ? "REAL IG DATA" : "SIMULATED DATA"}
            </span>
          </div>

          {/* Replay controls + live metrics */}
          {candles.length > 0 && live && (
            <div className="rounded-md border border-border bg-bg2 p-3">
              <div className="mb-2 flex flex-wrap items-center gap-3">
                <button onClick={() => { if (idx >= candles.length) setIdx(0); setPlaying((p) => !p); }} className="rounded bg-gold px-4 py-1.5 text-sm font-bold text-black hover:bg-gold2">
                  {playing ? "⏸ Pause" : idx >= candles.length ? "↻ Replay" : "▶ Play"}
                </button>
                <div className="flex overflow-hidden rounded border border-border font-mono text-[10px]">
                  {SPEEDS.map(([v, l]) => (
                    <button key={v} onClick={() => setSpeed(v)} className={`px-2 py-1 ${speed === v ? "bg-gold/15 text-gold" : "text-textmid hover:text-gold"}`}>{l}</button>
                  ))}
                </div>
                <input type="range" min={0} max={candles.length} value={idx} onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }} className="flex-1 accent-gold" />
                <span className="font-mono text-[11px] text-textdim">bar {live.bar}/{live.total}</span>
              </div>
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                <Live label="Time" value={live.date} small />
                <Live label="Equity" value={`£${live.equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}`} />
                <Live label="Return" value={`${live.ret >= 0 ? "+" : ""}${live.ret.toFixed(2)}%`} tone={live.ret >= 0 ? "up" : "down"} />
                <Live label="Max DD" value={`${live.maxDD.toFixed(2)}%`} tone="down" />
                <Live label="Trades" value={String(live.trades)} />
                <Live label="Win rate" value={`${live.winRate.toFixed(0)}%`} />
              </div>
            </div>
          )}

          <ReplayCharts candles={candles} equity={equity} trades={trades} idx={idx} />

          {/* Final summary */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Total return" value={pct(result.total_return_pct)} tone={(result.total_return_pct ?? 0) >= 0 ? "up" : "down"} />
            <Stat label="Trades" value={String(result.trades ?? 0)} />
            <Stat label="Win rate" value={`${result.win_rate ?? 0}%`} />
            <Stat label="Profit factor" value={String(result.profit_factor ?? 0)} />
            <Stat label="Avg R:R" value={String(result.avg_rr ?? 0)} />
            <Stat label="Expectancy/trade" value={pct(result.expectancy_pct)} />
            <Stat label="Max daily DD" value={`${result.max_daily_dd_pct ?? 0}%`} tone="down" />
            <Stat label="Max total DD" value={`${result.max_total_dd_pct ?? 0}%`} tone="down" />
          </div>

          {result.monte_carlo && Number(result.monte_carlo.runs ?? 0) > 0 && (
            <div className="rounded-md border border-border bg-bg2 p-4">
              <div className="mb-3 font-mono text-[10px] uppercase tracking-wider text-gold">
                // Monte Carlo ({result.monte_carlo.runs} runs · target {result.monte_carlo.target_pct}% · ruin {result.monte_carlo.total_limit_pct}%)
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                <Stat label="P(pass)" value={`${result.monte_carlo.pass_prob_pct}%`} tone="up" />
                <Stat label="P(breach)" value={`${result.monte_carlo.breach_prob_pct}%`} tone="down" />
                <Stat label="Median ret" value={`${result.monte_carlo.median_return_pct}%`} />
                <Stat label="P5 (bad)" value={`${result.monte_carlo.p5_return_pct}%`} />
                <Stat label="P95 (good)" value={`${result.monte_carlo.p95_return_pct}%`} />
              </div>
            </div>
          )}
        </>
      )}

      {!result && !running && (
        <div className="rounded-md border border-border bg-bg2 p-8 text-center font-mono text-xs text-textdim">
          Pick an instrument and run a backtest. It replays the strategy bar-by-bar with live equity and metrics.
          Real IG history when your engine is connected; otherwise simulated.
        </div>
      )}
    </div>
  );
}

/** Candle chart + equity area that reveal up to `idx`. */
function ReplayCharts({ candles, equity, trades, idx }: { candles: Candle[]; equity: EqPoint[]; trades: Trade[]; idx: number }) {
  const priceRef = useRef<HTMLDivElement>(null);
  const eqRef = useRef<HTMLDivElement>(null);
  const priceChart = useRef<any>(null);
  const candleSeries = useRef<any>(null);
  const eqChart = useRef<any>(null);
  const eqSeries = useRef<any>(null);

  useEffect(() => {
    let disposed = false;
    (async () => {
      const lib = await import("lightweight-charts");
      const base = { layout: { background: { color: "#0a0a0a" }, textColor: "#999" }, grid: { vertLines: { color: "#161616" }, horzLines: { color: "#161616" } }, timeScale: { timeVisible: true, borderColor: "#222" }, rightPriceScale: { borderColor: "#222" }, autoSize: true } as any;
      if (!disposed && priceRef.current) {
        const c = lib.createChart(priceRef.current, base);
        candleSeries.current = c.addCandlestickSeries({ upColor: "#22c55e", downColor: "#ef4444", borderVisible: false, wickUpColor: "#22c55e", wickDownColor: "#ef4444" });
        priceChart.current = c;
      }
      if (!disposed && eqRef.current) {
        const c = lib.createChart(eqRef.current, base);
        eqSeries.current = c.addAreaSeries({ lineColor: "#c9a84c", topColor: "rgba(201,168,76,0.25)", bottomColor: "rgba(201,168,76,0.02)", lineWidth: 2 });
        eqChart.current = c;
      }
    })();
    return () => { disposed = true; priceChart.current?.remove(); eqChart.current?.remove(); priceChart.current = eqChart.current = candleSeries.current = eqSeries.current = null; };
  }, []);

  useEffect(() => {
    const cs = candleSeries.current, es = eqSeries.current;
    if (!cs || !es) return;
    const dedupe = <T extends { time: number }>(rows: T[]) => { const seen = new Set<number>(); return [...rows].sort((a, b) => a.time - b.time).filter((r) => (seen.has(r.time) ? false : (seen.add(r.time), true))); };
    const shownC = dedupe(candles.slice(0, Math.max(1, idx)));
    cs.setData(shownC);
    const cut = shownC.length ? shownC[shownC.length - 1].time : 0;
    es.setData(dedupe(equity.filter((p) => p.time <= cut)).map((p) => ({ time: p.time, value: p.equity })));
    // trade markers up to cut
    const markers = trades
      .filter((t) => new Date(t.closed).getTime() / 1000 <= cut)
      .map((t) => ({ time: Math.floor(new Date(t.closed).getTime() / 1000), position: t.pnl >= 0 ? "belowBar" : "aboveBar", color: t.pnl >= 0 ? "#22c55e" : "#ef4444", shape: t.pnl >= 0 ? "arrowUp" : "arrowDown", text: `${t.pnl >= 0 ? "+" : ""}${t.pnl}` }));
    try { cs.setMarkers(markers as any); } catch { /* ignore */ }
  }, [idx, candles, equity, trades]);

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <div className="rounded-md border border-border bg-bg2">
        <div className="border-b border-border px-4 py-2 font-mono text-[10px] uppercase tracking-wider text-gold">// Price (with trade markers)</div>
        <div ref={priceRef} className="h-[280px] w-full" />
      </div>
      <div className="rounded-md border border-border bg-bg2">
        <div className="border-b border-border px-4 py-2 font-mono text-[10px] uppercase tracking-wider text-gold">// Equity curve</div>
        <div ref={eqRef} className="h-[280px] w-full" />
      </div>
    </div>
  );
}

// ── helpers ─────────────────────────────────────────────────────────────
function pct(v?: number) { return `${(v ?? 0) >= 0 ? "+" : ""}${v ?? 0}%`; }
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><div className="mb-1 font-mono text-[9px] uppercase tracking-wider text-textdim">{label}</div>{children}</div>;
}
function Select({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded border border-border bg-bg3 px-3 py-2 text-sm outline-none focus:border-gold">{options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>;
}
function NumberInput({ value, onChange, step }: { value: number; onChange: (v: number) => void; step: number }) {
  return <input type="number" step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-24 rounded border border-border bg-bg3 px-3 py-2 text-sm outline-none focus:border-gold" />;
}
function Stat({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  return <div className="rounded border border-border bg-bg3 px-3 py-2"><div className="font-mono text-[9px] uppercase tracking-wider text-textdim">{label}</div><div className={`mt-0.5 text-lg font-bold ${tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-gold"}`}>{value}</div></div>;
}
function Live({ label, value, tone, small }: { label: string; value: string; tone?: "up" | "down"; small?: boolean }) {
  return <div className="rounded border border-border bg-bg3 px-2 py-1.5"><div className="font-mono text-[8px] uppercase tracking-wider text-textdim">{label}</div><div className={`mt-0.5 font-bold ${small ? "text-[10px]" : "text-sm"} ${tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-textmid"}`}>{value}</div></div>;
}
