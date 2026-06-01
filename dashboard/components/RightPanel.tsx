"use client";

import { useState } from "react";
import type { AlgoState, LogEntry } from "@/lib/types";
import { UsageCost } from "./UsageCost";

type Tab = "usage" | "log";

const LEVEL_COLOUR: Record<string, string> = {
  ERROR: "text-down",
  WARNING: "text-gold",
  INFO: "text-textmid",
  DEBUG: "text-textdim",
};

/**
 * Tabbed side panel sharing the chart's height. Usage/Cost first, System Log last.
 */
export function RightPanel({ state }: { state: AlgoState }) {
  const [tab, setTab] = useState<Tab>("usage");

  return (
    <div className="flex h-full flex-col rounded-md border border-border bg-bg2">
      <div className="flex border-b border-border">
        <TabButton active={tab === "usage"} onClick={() => setTab("usage")}>Usage / Cost</TabButton>
        <TabButton active={tab === "log"} onClick={() => setTab("log")}>System Log</TabButton>
      </div>
      <div className="min-h-0 flex-1">
        {tab === "usage" ? <UsageCost state={state} /> : <LogBody logs={state.logs} />}
      </div>
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 font-mono text-[10px] uppercase tracking-wider transition ${
        active ? "border-b-2 border-gold text-gold" : "text-textdim hover:text-textmid"
      }`}
    >
      {children}
    </button>
  );
}

function LogBody({ logs }: { logs: LogEntry[] }) {
  const ordered = [...logs].reverse(); // newest first
  return (
    <div className="h-full overflow-y-auto p-3 font-mono text-[11px] leading-relaxed">
      {ordered.length === 0 ? (
        <div className="text-textdim">No log entries yet.</div>
      ) : (
        ordered.map((l, i) => (
          <div key={i} className="flex gap-2 py-0.5">
            <span className="shrink-0 text-textdim">{new Date(l.time).toLocaleTimeString()}</span>
            <span className={`shrink-0 ${LEVEL_COLOUR[l.level] ?? "text-textmid"}`}>{l.level.slice(0, 4)}</span>
            <span className="text-textmid">{l.message}</span>
          </div>
        ))
      )}
    </div>
  );
}
