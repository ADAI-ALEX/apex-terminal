"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { AlgoState } from "@/lib/types";

type SeriesBag = {
  price: any;
  ema9: any;
  ema21: any;
  ema55: any;
};

/**
 * Rolling real-time chart. The state stream carries indicator snapshots (not full
 * candle history), so we accumulate a line of the latest price + EMAs per tick.
 * Uses TradingView Lightweight Charts v4 (chart.addLineSeries).
 */
export function LiveChart({ state }: { state: AlgoState }) {
  const markets = useMemo(() => Object.keys(state.indicators), [state.indicators]);
  const [selected, setSelected] = useState<string>(markets[0] ?? "");

  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const seriesRef = useRef<SeriesBag | null>(null);
  const lastTimeRef = useRef<number>(0);

  const active = selected && markets.includes(selected) ? selected : markets[0];
  const snap = active ? state.indicators[active] : undefined;

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
        timeScale: { timeVisible: true, secondsVisible: true, borderColor: "#222" },
        rightPriceScale: { borderColor: "#222" },
      });
      seriesRef.current = {
        price: chart.addLineSeries({ color: "#e8c97a", lineWidth: 2 }),
        ema9: chart.addLineSeries({ color: "#3b82f6", lineWidth: 1 }),
        ema21: chart.addLineSeries({ color: "#a855f7", lineWidth: 1 }),
        ema55: chart.addLineSeries({ color: "#555555", lineWidth: 1 }),
      };
      chartRef.current = chart;
    })();
    return () => {
      disposed = true;
      chartRef.current?.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Reset the lines when the selected market changes.
  useEffect(() => {
    const s = seriesRef.current;
    if (!s) return;
    s.price.setData([]);
    s.ema9.setData([]);
    s.ema21.setData([]);
    s.ema55.setData([]);
    lastTimeRef.current = 0;
  }, [active]);

  // Append the latest tick.
  useEffect(() => {
    const s = seriesRef.current;
    if (!s || !snap) return;
    const t = Math.floor(new Date(state.server_time).getTime() / 1000);
    if (t < lastTimeRef.current) return;
    lastTimeRef.current = t;
    s.price.update({ time: t, value: snap.price });
    if (snap.ema_fast) s.ema9.update({ time: t, value: snap.ema_fast });
    if (snap.ema_mid) s.ema21.update({ time: t, value: snap.ema_mid });
    if (snap.ema_slow) s.ema55.update({ time: t, value: snap.ema_slow });
  }, [state.server_time, snap]);

  return (
    <div className="rounded-md border border-border bg-bg2">
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-gold">
          // Live Chart
        </span>
        <select
          value={active}
          onChange={(e) => setSelected(e.target.value)}
          className="rounded border border-border bg-bg3 px-2 py-1 font-mono text-[11px] text-textmid outline-none"
        >
          {markets.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>

      <div ref={containerRef} className="h-[300px] w-full" />

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

function Metric({
  label,
  value,
  accent,
}: {
  label: string;
  value?: string | number;
  accent?: boolean;
}) {
  return (
    <div className="bg-bg3 px-3 py-2">
      <div className="font-mono text-[9px] uppercase tracking-wider text-textdim">
        {label}
      </div>
      <div className={`text-sm ${accent ? "text-gold" : "text-textmid"}`}>{value}</div>
    </div>
  );
}
