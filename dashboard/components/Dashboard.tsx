"use client";

import { useRef, useState } from "react";
import { useStream } from "./useStream";
import { StatusBar } from "./StatusBar";
import { Overview } from "./Overview";
import { Positions } from "./Positions";
import { LiveChart } from "./LiveChart";
import { RightPanel } from "./RightPanel";

export function Dashboard() {
  const { state, status } = useStream();

  // Resizable split between the chart and the side panel (chart % of the row width).
  const [split, setSplit] = useState(64);
  const rowRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  function startDrag(e: React.MouseEvent) {
    e.preventDefault();
    dragging.current = true;
    const onMove = (ev: MouseEvent) => {
      if (!dragging.current || !rowRef.current) return;
      const rect = rowRef.current.getBoundingClientRect();
      const pct = ((ev.clientX - rect.left) / rect.width) * 100;
      setSplit(Math.min(80, Math.max(40, pct)));
    };
    const onUp = () => {
      dragging.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  if (!state) {
    return (
      <div className="mx-auto max-w-md rounded-md border border-border bg-bg2 p-6 text-center">
        <div className="mb-2 font-mono text-sm text-gold">Waiting for your trading engine…</div>
        <p className="text-sm text-textmid">
          Your config is saved. Now start the engine on your machine and leave it running:
        </p>
        <p className="mt-3 rounded border border-border bg-bg3 px-3 py-2 font-mono text-xs text-textmid">
          double-click <span className="text-gold">start.bat</span>
        </p>
        <p className="mt-3 text-xs text-textdim">
          Live data appears here within ~30s of the engine connecting. This page keeps retrying.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {state.broker_error && (
        <div className="rounded-md border border-down/40 bg-down/10 px-4 py-3 text-sm text-down">
          <span className="font-bold">Broker not connected — running in simulation.</span>{" "}
          {state.broker_error} Fix it in <a href="/settings" className="underline">Settings</a>.
        </div>
      )}
      <StatusBar state={state} status={status} />
      <Overview state={state} />

      {/* Desktop: resizable chart | side panel, equal height */}
      <div ref={rowRef} className="hidden h-[460px] lg:flex">
        <div style={{ width: `${split}%` }} className="min-w-0">
          <LiveChart state={state} />
        </div>
        <div
          onMouseDown={startDrag}
          title="Drag to resize"
          className="mx-1 w-1.5 shrink-0 cursor-col-resize rounded bg-border transition hover:bg-gold"
        />
        <div className="min-w-0 flex-1">
          <RightPanel state={state} />
        </div>
      </div>

      {/* Mobile / tablet: stacked */}
      <div className="space-y-4 lg:hidden">
        <div className="h-[360px]"><LiveChart state={state} /></div>
        <div className="h-[360px]"><RightPanel state={state} /></div>
      </div>

      <Positions positions={state.positions} />
    </div>
  );
}
