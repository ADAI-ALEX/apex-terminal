"use client";

import type { LogEntry } from "@/lib/types";

const LEVEL_COLOUR: Record<string, string> = {
  ERROR: "text-down",
  WARNING: "text-gold",
  INFO: "text-textmid",
  DEBUG: "text-textdim",
};

export function SystemLog({ logs }: { logs: LogEntry[] }) {
  const ordered = [...logs].reverse(); // newest first

  return (
    <div className="flex h-full flex-col rounded-md border border-border bg-bg2">
      <div className="border-b border-border px-4 py-3 font-mono text-[10px] uppercase tracking-wider text-gold">
        // System Log
      </div>
      <div className="max-h-[360px] flex-1 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed">
        {ordered.length === 0 ? (
          <div className="text-textdim">No log entries yet.</div>
        ) : (
          ordered.map((l, i) => (
            <div key={i} className="flex gap-2 py-0.5">
              <span className="shrink-0 text-textdim">
                {new Date(l.time).toLocaleTimeString()}
              </span>
              <span className={`shrink-0 ${LEVEL_COLOUR[l.level] ?? "text-textmid"}`}>
                {l.level.slice(0, 4)}
              </span>
              <span className="text-textmid">{l.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
