"use client";

import type { AlgoState } from "@/lib/types";
import type { StreamStatus } from "./useStream";

const BREAKER_LABELS: Record<string, string> = {
  daily_loss: "Daily loss",
  weekly_loss: "Weekly halt",
  max_positions: "Max positions",
  consecutive_losses: "Loss streak",
  trading_disabled: "Trading off",
};

export function StatusBar({
  state,
  status,
}: {
  state: AlgoState;
  status: StreamStatus;
}) {
  const halted = state.status === "HALTED" || !state.trading_enabled;
  const heartbeatAge = Math.round(
    (Date.now() - new Date(state.last_heartbeat).getTime()) / 1000,
  );

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-bg2 px-4 py-3 font-mono text-[11px]">
      <Pill
        label={state.status}
        tone={halted ? "down" : state.mode === "PAPER" ? "info" : "up"}
      />
      <span className="text-textdim">
        stream:{" "}
        <span className={status === "live" ? "text-up" : "text-down"}>
          {status}
        </span>
      </span>
      <span className="text-textdim">
        heartbeat: <span className="text-textmid">{heartbeatAge}s ago</span>
      </span>
      <span className="text-textdim">
        IG calls: <span className="text-textmid">{state.api_calls.ig ?? 0}</span>
      </span>
      <span className="text-textdim">
        Claude calls:{" "}
        <span className="text-textmid">{state.api_calls.claude ?? 0}</span>
      </span>

      <div className="ml-auto flex flex-wrap gap-2">
        {Object.entries(state.breakers).map(([key, tripped]) => (
          <span
            key={key}
            className={`rounded px-2 py-0.5 ${
              tripped
                ? "bg-down/10 text-down"
                : "bg-up/10 text-up"
            }`}
            title={tripped ? "Tripped" : "OK"}
          >
            {BREAKER_LABELS[key] ?? key}
          </span>
        ))}
      </div>
    </div>
  );
}

function Pill({ label, tone }: { label: string; tone: "up" | "down" | "info" }) {
  const colour =
    tone === "up"
      ? "bg-up/10 text-up"
      : tone === "down"
        ? "bg-down/10 text-down"
        : "bg-info/10 text-info";
  return (
    <span className={`rounded px-2 py-0.5 font-bold uppercase ${colour}`}>
      {label}
    </span>
  );
}
