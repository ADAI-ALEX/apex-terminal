"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { AlgoState } from "@/lib/types";

type ChartMode = "candles" | "line";

/**
 * Live chart body (chrome supplied by the widget frame). Candlesticks/line from the
 * OHLC history the engine publishes in `state.candles`. The instrument list comes from
 * the markets selected in Settings (`state.markets`). Shows a loader until data arrives.
 */
export function LiveChart({ state }: { state: AlgoState }) {
  const markets = useMemo(() => {
    const selected = state.markets ?? [];
    const withData = Object.keys(state.candles ?? {});
    const merged = selected.length ? selected : withData;
    // include any market that has data but isn't listed, just in case
    for (const m of withData) if (!merged.includes(m)) merged.push(m);
    return merged.length ? merged : Object.keys(state.indicators ?? {});
  }, [state.markets, state.candles, state.indicators]);

  const [selected, setSelected] = useState<string>("");
  const [mode, setMode] = useState<ChartMode>("candles");

  const wrapRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const candleRef = useRef<any>(null);
  const lineRef = useRef<any>(null);

  const active = selected && markets.includes(selected) ? selected : markets[0] ?? "";
  const snap = active ? state.indicators?.[active] : undefined;
  const ohlc = active ? state.candles?.[active] ?? [] : [];
  const loading = active !== "" && ohlc.length === 0;

  useEffect(() => {
    let disposed = false;
    (async () => {
      const lib = await import("lightweight-charts");
      if (disposed || !containerRef.current) return;
      const chart = lib.createChart(containerRef.current, {
        autoSize: true,
        layout: { background: { color: "#0a0a0a" }, textColor: "#999" },
        grid: { vertLines: { color: "#161616" }, horzLines: { color: "#161616" } },
        timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#222" },
        rightPriceScale: { borderColor: "#222" },
        crosshair: { mode: 0 },
      });
      candleRef.current = chart.addCandlestickSeries({
        upColor: "#22c55e", downColor: "#ef4444", borderVisible: false,
        wickUpColor: "#22c55e", wickDownColor: "#ef4444",
      });
      lineRef.current = chart.addLineSeries({ color: "#e8c97a", lineWidth: 2 });
      chartRef.current = chart;
    })();
    return () => {
      disposed = true;
      chartRef.current?.remove();
      chartRef.current = null;
      candleRef.current = null;
      lineRef.current = null;
    };
  }, []);

  useEffect(() => {
    const candle = candleRef.current;
    const line = lineRef.current;
    if (!candle || !line) return;
    const seen = new Set<number>();
    const rows = [...ohlc]
      .sort((a, b) => a.time - b.time)
      .filter((c) => (seen.has(c.time) ? false : (seen.add(c.time), true)));
    if (mode === "candles") {
      candle.setData(rows);
      line.setData([]);
    } else {
      candle.setData([]);
      line.setData(rows.map((c) => ({ time: c.time, value: c.close })));
    }
    if (rows.length) chartRef.current?.timeScale().fitContent();
  }, [ohlc, mode, active]);

  function toggleFullscreen() {
    const el = wrapRef.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.();
  }

  return (
    <div ref={wrapRef} className="flex h-full flex-col bg-bg2">
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
        <select
          value={active}
          onChange={(e) => setSelected(e.target.value)}
          className="rounded border border-border bg-bg3 px-2 py-1 font-mono text-[11px] text-textmid outline-none focus:border-gold"
        >
          {markets.length === 0 && <option value="">No instruments</option>}
          {markets.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
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
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-bg2/80">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-border border-t-gold" />
            <div className="font-mono text-xs text-textmid">Loading {active} candles…</div>
          </div>
        )}
        {!loading && markets.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center font-mono text-xs text-textdim">
            No instruments selected — choose some in Settings.
          </div>
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
