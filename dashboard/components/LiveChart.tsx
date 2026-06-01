"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { AlgoState } from "@/lib/types";

type ChartMode = "candles" | "line";

/**
 * Live chart driven by the OHLC candle history the engine publishes in
 * `state.candles`. Supports candlestick / line view, instrument switching, and
 * fullscreen. Uses TradingView Lightweight Charts v4.
 */
export function LiveChart({ state }: { state: AlgoState }) {
  const markets = useMemo(() => {
    const fromCandles = Object.keys(state.candles ?? {});
    return fromCandles.length ? fromCandles : Object.keys(state.indicators ?? {});
  }, [state.candles, state.indicators]);

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

  // Mount the chart once.
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

  // Push data whenever the candles, market, or mode change.
  useEffect(() => {
    const candle = candleRef.current;
    const line = lineRef.current;
    if (!candle || !line) return;

    // De-dup + sort by time (lightweight-charts requires strictly ascending unique times).
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
    chartRef.current?.timeScale().fitContent();
  }, [ohlc, mode, active]);

  function toggleFullscreen() {
    const el = wrapRef.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.();
  }

  return (
    <div ref={wrapRef} className="flex h-full flex-col rounded-md border border-border bg-bg2">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-gold">// Live Chart</span>
        <div className="flex items-center gap-2">
          <select
            value={active}
            onChange={(e) => setSelected(e.target.value)}
            className="rounded border border-border bg-bg3 px-2 py-1 font-mono text-[11px] text-textmid outline-none focus:border-gold"
          >
            {markets.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
          <div className="flex overflow-hidden rounded border border-border font-mono text-[10px]">
            <button
              onClick={() => setMode("candles")}
              className={`px-2 py-1 ${mode === "candles" ? "bg-gold/15 text-gold" : "text-textmid hover:text-gold"}`}
            >
              Candles
            </button>
            <button
              onClick={() => setMode("line")}
              className={`border-l border-border px-2 py-1 ${mode === "line" ? "bg-gold/15 text-gold" : "text-textmid hover:text-gold"}`}
            >
              Line
            </button>
          </div>
          <button
            onClick={toggleFullscreen}
            title="Fullscreen"
            className="rounded border border-border px-2 py-1 font-mono text-[11px] text-textmid transition hover:border-gold hover:text-gold"
          >
            ⛶
          </button>
        </div>
      </div>

      <div className="relative flex-1">
        <div ref={containerRef} className="absolute inset-0" />
        {ohlc.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center font-mono text-xs text-textdim">
            No candle data yet — waiting for the engine to publish prices…
          </div>
        )}
      </div>

      {snap && (
        <div className="grid grid-cols-2 gap-px border-t border-border bg-border sm:grid-cols-5">
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
    <div className="bg-bg3 px-3 py-2">
      <div className="font-mono text-[9px] uppercase tracking-wider text-textdim">{label}</div>
      <div className={`text-sm ${accent ? "text-gold" : "text-textmid"}`}>{value}</div>
    </div>
  );
}
