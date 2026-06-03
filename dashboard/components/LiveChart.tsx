"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AlgoState } from "@/lib/types";
import { chartColors } from "@/lib/theme";

type ChartMode = "candles" | "line";
type Candle = { time: number; open: number; high: number; low: number; close: number };

const INTERVALS: [string, string][] = [["5m", "5m"], ["15m", "15m"], ["1h", "1H"], ["1d", "1D"]];

/**
 * Price chart. Candles come from /api/prices (Yahoo Finance proxy — free, fast, no
 * key), so it loads instantly and switching instrument/interval is snappy. Falls back
 * to the engine's streamed candles if the upstream is unavailable. Indicator readouts
 * come from the algo's live state.
 */
export function LiveChart({ state }: { state: AlgoState }) {
  const markets = useMemo(() => {
    const sel = state.markets ?? [];
    const withData = Object.keys(state.candles ?? {});
    const merged = sel.length ? [...sel] : [...withData];
    for (const m of withData) if (!merged.includes(m)) merged.push(m);
    return merged.length ? merged : Object.keys(state.indicators ?? {});
  }, [state.markets, state.candles, state.indicators]);

  const [selected, setSelected] = useState("");
  const [interval, setInterval_] = useState("15m");
  const [mode, setMode] = useState<ChartMode>("candles");
  const [loading, setLoading] = useState(false);
  const [empty, setEmpty] = useState(false);
  const [chartReady, setChartReady] = useState(false);

  const active = selected && markets.includes(selected) ? selected : markets[0] ?? "";
  const snap = active ? state.indicators?.[active] : undefined;

  const wrapRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const candleRef = useRef<any>(null);
  const lineRef = useRef<any>(null);
  const fittedFor = useRef("");
  const dataRef = useRef<Candle[]>([]);
  // Always read the freshest engine state for the candles fallback: the fetch effect
  // closes over this ref (not the prop), so late-arriving KV candles are still used.
  const stateRef = useRef(state);
  stateRef.current = state;
  // Remembers whether the whole terminal was already fullscreen when the chart was
  // expanded, so leaving chart-fullscreen returns there (not all the way to normal).
  const fsOriginRef = useRef<"normal" | "term">("normal");

  // Mount the chart with an explicit ResizeObserver (reliable fill on resize/zoom).
  useEffect(() => {
    let disposed = false;
    let ro: ResizeObserver | null = null;
    let cleanupTheme: (() => void) | null = null;
    (async () => {
      const lib = await import("lightweight-charts");
      if (disposed || !containerRef.current) return;
      const el = containerRef.current;
      const c0 = chartColors();
      const chart = lib.createChart(el, {
        width: el.clientWidth || 320, height: el.clientHeight || 200,
        layout: { background: { color: c0.bg }, textColor: c0.text },
        grid: { vertLines: { color: c0.grid }, horzLines: { color: c0.grid } },
        timeScale: { timeVisible: true, secondsVisible: false, borderColor: c0.border },
        rightPriceScale: { borderColor: c0.border },
        crosshair: { mode: 0 },
        handleScroll: true, handleScale: true,
      });
      candleRef.current = chart.addCandlestickSeries({ upColor: "#22c55e", downColor: "#ef4444", borderVisible: false, wickUpColor: "#22c55e", wickDownColor: "#ef4444" });
      lineRef.current = chart.addLineSeries({ color: "#c9a84c", lineWidth: 2 });
      chartRef.current = chart;
      ro = new ResizeObserver(() => { const w = el.clientWidth, h = el.clientHeight; if (w > 0 && h > 0) chart.resize(w, h); });
      ro.observe(el);
      const onTheme = () => {
        const c = chartColors();
        chart.applyOptions({ layout: { background: { color: c.bg }, textColor: c.text }, grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } }, timeScale: { borderColor: c.border }, rightPriceScale: { borderColor: c.border } });
      };
      window.addEventListener("apex-theme", onTheme);
      cleanupTheme = () => window.removeEventListener("apex-theme", onTheme);
      setChartReady(true); // signal the data effect that the series exist now
    })();
    return () => { disposed = true; setChartReady(false); ro?.disconnect(); cleanupTheme?.(); chartRef.current?.remove(); chartRef.current = candleRef.current = lineRef.current = null; };
  }, []);

  // Paint the current dataset into the series. Safe to call any time — it no-ops until
  // the (async-imported) chart exists, then the readiness effect calls it again. This
  // decoupling is the real blank-chart fix: drawing never depends on the fetch winning
  // a race against the chart mount (the previous chartReady *gate* could stay stuck).
  const redraw = useCallback(() => {
    const candle = candleRef.current, line = lineRef.current;
    if (!candle || !line) return;
    const rows = dataRef.current;
    setEmpty(rows.length === 0);
    if (mode === "candles") { candle.setData(rows); line.setData([]); }
    else { candle.setData([]); line.setData(rows.map((c) => ({ time: c.time, value: c.close }))); }
    const key = `${active}:${interval}:${mode}`;
    if (rows.length && fittedFor.current !== key) {
      fittedFor.current = key;
      // Fit on the next frame so the price + time scales size to the freshly-set data.
      requestAnimationFrame(() => chartRef.current?.timeScale().fitContent());
    }
  }, [active, interval, mode]);
  const redrawRef = useRef(redraw);
  redrawRef.current = redraw;

  // Re-draw when the chart becomes ready (mount) or the draw config changes (mode).
  useEffect(() => { redraw(); }, [redraw, chartReady]);

  // Fetch candles whenever instrument or interval changes (and refresh every 60s).
  // Independent of chart readiness: results land in dataRef and redraw() paints them
  // whenever the chart is up — so neither order (fetch-first or chart-first) goes blank.
  useEffect(() => {
    if (!active) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;

    const apply = (rows: Candle[]) => {
      const seen = new Set<number>();
      dataRef.current = [...rows]
        .sort((a, b) => a.time - b.time)
        .filter((c) => (seen.has(c.time) ? false : (seen.add(c.time), true)));
      if (alive) redrawRef.current();
    };

    const load = async (showSpinner: boolean) => {
      if (showSpinner) setLoading(true);
      try {
        const res = await fetch(`/api/prices?symbol=${encodeURIComponent(active)}&interval=${interval}`, { cache: "no-store" });
        const j = await res.json();
        let rows: Candle[] = Array.isArray(j.candles) ? j.candles : [];
        if (!rows.length) rows = (stateRef.current.candles?.[active] ?? []) as Candle[]; // fallback: engine candles
        apply(rows);
      } catch {
        apply((stateRef.current.candles?.[active] ?? []) as Candle[]); // network down → engine candles
      } finally {
        if (alive && showSpinner) setLoading(false);
      }
    };

    void load(true);
    const tick = () => { void load(false); timer = setTimeout(tick, 60_000); };
    timer = setTimeout(tick, 60_000);
    return () => { alive = false; clearTimeout(timer); };
  }, [active, interval]);

  // Expand JUST the chart to the whole screen. If the terminal was already fullscreen,
  // leaving chart-fullscreen (via this button) returns to the fullscreen terminal; if it
  // wasn't, it returns to the normal window. (Uses the Fullscreen API, which ignores the
  // React Flow canvas transform, so the chart truly fills the monitor.)
  function toggleFullscreen() {
    const el = wrapRef.current;
    if (!el) return;
    const root = el.closest("[data-apex-root]") as HTMLElement | null;
    if (document.fullscreenElement === el) {
      const restoreTerm = fsOriginRef.current === "term" && !!root;
      fsOriginRef.current = "normal";
      void document.exitFullscreen()
        .then(() => { if (restoreTerm) root!.requestFullscreen?.().catch(() => {}); })
        .catch(() => {});
    } else {
      fsOriginRef.current = document.fullscreenElement ? "term" : "normal";
      void el.requestFullscreen?.().catch(() => {});
    }
  }

  return (
    <div ref={wrapRef} className="flex h-full flex-col bg-bg2">
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
        <div className="flex items-center gap-2">
          <select value={active} onChange={(e) => setSelected(e.target.value)} className="rounded border border-border bg-bg3 px-2 py-1 font-mono text-[11px] text-textmid outline-none focus:border-gold">
            {markets.length === 0 && <option value="">No instruments</option>}
            {markets.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <div className="flex overflow-hidden rounded border border-border font-mono text-[10px]">
            {INTERVALS.map(([v, l]) => (
              <button key={v} onClick={() => setInterval_(v)} className={`px-2 py-1 ${interval === v ? "bg-gold/15 text-gold" : "text-textmid hover:text-gold"}`}>{l}</button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex overflow-hidden rounded border border-border font-mono text-[10px]">
            <button onClick={() => setMode("candles")} className={`px-2 py-1 ${mode === "candles" ? "bg-gold/15 text-gold" : "text-textmid hover:text-gold"}`}>Candles</button>
            <button onClick={() => setMode("line")} className={`border-l border-border px-2 py-1 ${mode === "line" ? "bg-gold/15 text-gold" : "text-textmid hover:text-gold"}`}>Line</button>
          </div>
          <button onClick={toggleFullscreen} title="Fullscreen" className="rounded border border-border px-2 py-1 font-mono text-[11px] text-textmid transition hover:border-gold hover:text-gold">⛶</button>
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        <div ref={containerRef} className="absolute inset-0" />
        {loading && (
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 bg-bg2/70">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-border border-t-gold" />
            <div className="font-mono text-[11px] text-textmid">Loading {active}…</div>
          </div>
        )}
        {!loading && empty && (
          <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] text-textdim">No data for {active} at {interval}.</div>
        )}
      </div>

      {snap && (
        <div className="grid grid-cols-5 gap-px border-t border-border bg-border">
          <Metric label="Price" value={snap.price?.toFixed(2)} />
          <Metric label="RSI" value={snap.rsi?.toFixed(1) ?? "—"} />
          <Metric label="ATR" value={snap.atr?.toFixed(2) ?? "—"} />
          <Metric label="ADX" value={snap.adx?.toFixed(1) ?? "—"} />
          <Metric label="Regime" value={snap.regime ?? "—"} accent />
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, accent }: { label: string; value?: string | number; accent?: boolean }) {
  return (
    <div className="bg-bg3 px-2 py-1.5">
      <div className="font-mono text-[8px] uppercase tracking-wider text-textdim">{label}</div>
      <div className={`text-xs ${accent ? "text-gold" : "text-textmid"}`}>{value}</div>
    </div>
  );
}
