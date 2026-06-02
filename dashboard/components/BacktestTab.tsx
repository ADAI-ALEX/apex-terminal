"use client";

import { useEffect, useRef, useState } from "react";

type Result = {
  error?: string;
  pending?: boolean;
  mode?: string;
  market?: string;
  bars?: number;
  minutes?: number;
  starting_equity?: number;
  final_equity?: number;
  total_return_pct?: number;
  trades?: number;
  win_rate?: number;
  profit_factor?: number;
  avg_rr?: number;
  expectancy_pct?: number;
  max_daily_dd_pct?: number;
  max_total_dd_pct?: number;
  equity_curve?: { time: number; equity: number }[];
  trade_log?: { market: string; direction: string; entry: number; exit: number; pnl: number; ret_pct: number; reason: string; strategy: string; closed: string }[];
  monte_carlo?: Record<string, number | string>;
};

const MARKETS = ["US500", "NAS100", "EURUSD", "GBPUSD", "FTSE100", "DAX40"];
const TIMEFRAMES: [number, string][] = [[5, "5m"], [15, "15m"], [30, "30m"], [60, "1h"]];

export function BacktestTab() {
  const [market, setMarket] = useState("US500");
  const [minutes, setMinutes] = useState(15);
  const [bars, setBars] = useState(500);
  const [riskPct, setRiskPct] = useState(0.4);
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState("");
  const [result, setResult] = useState<Result | null>(null);

  async function run() {
    setRunning(true);
    setResult(null);
    setStatus("Submitting backtest…");
    try {
      const res = await fetch("/api/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ market, minutes, bars, risk_pct: riskPct, target_pct: 10, total_limit_pct: 10 }),
      });
      const data = (await res.json()) as Result & { id?: string; queued?: boolean };

      if (data.queued && data.id) {
        // Cloud relay: poll for the laptop's result.
        setStatus("Running on your engine (real data)…");
        const deadline = Date.now() + 120_000;
        while (Date.now() < deadline) {
          await new Promise((r) => setTimeout(r, 2500));
          const poll = await fetch(`/api/backtest?id=${data.id}`, { cache: "no-store" });
          const pj = (await poll.json()) as Result;
          if (!pj.pending) { finish(pj); return; }
          setStatus("Running on your engine (real data)…");
        }
        setStatus("Timed out — is the engine running (start.bat)?");
        setRunning(false);
        return;
      }
      finish(data); // local synchronous result
    } catch (e) {
      setStatus("Request failed.");
      setRunning(false);
    }
  }

  function finish(r: Result) {
    setRunning(false);
    setStatus("");
    setResult(r);
  }

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="rounded-md border border-border bg-bg2 p-4">
        <div className="mb-3 font-mono text-[10px] uppercase tracking-wider text-gold">// Backtest — strategy book on historical data</div>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Instrument">
            <Select value={market} onChange={setMarket} options={MARKETS.map((m) => [m, m])} />
          </Field>
          <Field label="Timeframe">
            <Select value={String(minutes)} onChange={(v) => setMinutes(Number(v))} options={TIMEFRAMES.map(([v, l]) => [String(v), l])} />
          </Field>
          <Field label="Bars">
            <NumberInput value={bars} onChange={setBars} step={50} />
          </Field>
          <Field label="Risk %/trade">
            <NumberInput value={riskPct} onChange={setRiskPct} step={0.1} />
          </Field>
          <button
            onClick={run}
            disabled={running}
            className="rounded bg-gold px-6 py-2 text-sm font-bold text-black transition hover:bg-gold2 disabled:opacity-50"
          >
            {running ? "Running…" : "Run backtest"}
          </button>
          {status && <span className="font-mono text-xs text-textmid">{status}</span>}
        </div>
      </div>

      {result?.error && (
        <div className="rounded-md border border-down/40 bg-down/10 px-4 py-3 text-sm text-down">{result.error}</div>
      )}

      {result && !result.error && (
        <>
          <div className="flex items-center gap-3">
            <span className="font-mono text-sm text-textmid">{result.market} · {result.minutes}m · {result.bars} bars</span>
            <span className={`rounded px-2 py-0.5 font-mono text-[10px] ${result.mode === "IG" ? "bg-up/10 text-up" : "bg-info/10 text-info"}`}>
              {result.mode === "IG" ? "REAL IG DATA" : "SIMULATED DATA"}
            </span>
          </div>

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

          <EquityChart points={result.equity_curve ?? []} />

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

          <TradeLog trades={result.trade_log ?? []} />
        </>
      )}

      {!result && !running && (
        <div className="rounded-md border border-border bg-bg2 p-8 text-center font-mono text-xs text-textdim">
          Pick an instrument and run a backtest. Results use real IG history when your
          engine is connected to IG; otherwise simulated data.
        </div>
      )}
    </div>
  );
}

function EquityChart({ points }: { points: { time: number; equity: number }[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const seriesRef = useRef<any>(null);

  useEffect(() => {
    let disposed = false;
    (async () => {
      const lib = await import("lightweight-charts");
      if (disposed || !ref.current) return;
      const chart = lib.createChart(ref.current, {
        autoSize: true,
        layout: { background: { color: "#0a0a0a" }, textColor: "#999" },
        grid: { vertLines: { color: "#161616" }, horzLines: { color: "#161616" } },
        timeScale: { timeVisible: true, borderColor: "#222" },
        rightPriceScale: { borderColor: "#222" },
      });
      seriesRef.current = chart.addAreaSeries({ lineColor: "#c9a84c", topColor: "rgba(201,168,76,0.25)", bottomColor: "rgba(201,168,76,0.02)", lineWidth: 2 });
      chartRef.current = chart;
      pushData();
    })();
    return () => { disposed = true; chartRef.current?.remove(); chartRef.current = null; seriesRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function pushData() {
    const s = seriesRef.current;
    if (!s) return;
    const seen = new Set<number>();
    const rows = [...points].sort((a, b) => a.time - b.time).filter((p) => (seen.has(p.time) ? false : (seen.add(p.time), true)));
    s.setData(rows.map((p) => ({ time: p.time, value: p.equity })));
    chartRef.current?.timeScale().fitContent();
  }
  useEffect(() => { pushData(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [points]);

  return (
    <div className="rounded-md border border-border bg-bg2">
      <div className="border-b border-border px-4 py-2 font-mono text-[10px] uppercase tracking-wider text-gold">// Equity curve</div>
      <div ref={ref} className="h-[300px] w-full" />
    </div>
  );
}

function TradeLog({ trades }: { trades: Result["trade_log"] }) {
  const list = trades ?? [];
  return (
    <div className="rounded-md border border-border bg-bg2">
      <div className="border-b border-border px-4 py-2 font-mono text-[10px] uppercase tracking-wider text-gold">// Trades ({list.length})</div>
      <div className="max-h-[300px] overflow-y-auto">
        <table className="w-full font-mono text-[11px]">
          <thead className="sticky top-0 bg-bg2 text-textdim">
            <tr className="border-b border-border">
              <th className="px-3 py-1.5 text-left">Closed</th><th className="text-left">Dir</th>
              <th className="text-right">Entry</th><th className="text-right">Exit</th>
              <th className="text-right">P&amp;L</th><th className="text-right">Ret</th>
              <th className="text-left">Why</th><th className="text-left">Strategy</th>
            </tr>
          </thead>
          <tbody>
            {list.length === 0 ? (
              <tr><td colSpan={8} className="px-3 py-3 text-center text-textdim">No trades in this window.</td></tr>
            ) : list.slice().reverse().map((t, i) => (
              <tr key={i} className="border-b border-border/50">
                <td className="px-3 py-1 text-textdim">{new Date(t.closed).toLocaleDateString()}</td>
                <td className={t.direction === "BUY" ? "text-up" : "text-down"}>{t.direction}</td>
                <td className="text-right text-textmid">{t.entry}</td>
                <td className="text-right text-textmid">{t.exit}</td>
                <td className={`text-right ${t.pnl >= 0 ? "text-up" : "text-down"}`}>{t.pnl}</td>
                <td className={`text-right ${t.ret_pct >= 0 ? "text-up" : "text-down"}`}>{t.ret_pct}%</td>
                <td className="text-textdim">{t.reason}</td>
                <td className="text-textmid">{t.strategy}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── small helpers ──────────────────────────────────────────────────────
function pct(v?: number) { return `${(v ?? 0) >= 0 ? "+" : ""}${v ?? 0}%`; }

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 font-mono text-[9px] uppercase tracking-wider text-textdim">{label}</div>
      {children}
    </div>
  );
}
function Select({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded border border-border bg-bg3 px-3 py-2 text-sm outline-none focus:border-gold">
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
}
function NumberInput({ value, onChange, step }: { value: number; onChange: (v: number) => void; step: number }) {
  return (
    <input type="number" step={step} value={value} onChange={(e) => onChange(Number(e.target.value))}
      className="w-24 rounded border border-border bg-bg3 px-3 py-2 text-sm outline-none focus:border-gold" />
  );
}
function Stat({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  return (
    <div className="rounded border border-border bg-bg3 px-3 py-2">
      <div className="font-mono text-[9px] uppercase tracking-wider text-textdim">{label}</div>
      <div className={`mt-0.5 text-lg font-bold ${tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-gold"}`}>{value}</div>
    </div>
  );
}
