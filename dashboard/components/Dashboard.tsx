"use client";

import { useStream } from "./useStream";
import { StatusBar } from "./StatusBar";
import { Overview } from "./Overview";
import { Positions } from "./Positions";
import { SystemLog } from "./SystemLog";
import { LiveChart } from "./LiveChart";

export function Dashboard() {
  const { state, status } = useStream();

  if (!state) {
    return (
      <div className="flex h-64 items-center justify-center font-mono text-sm text-textmid">
        {status === "error"
          ? "Cannot reach the algo state server. Is the VPS running?"
          : "Connecting to algo…"}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <StatusBar state={state} status={status} />
      <Overview state={state} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <LiveChart state={state} />
        </div>
        <SystemLog logs={state.logs} />
      </div>
      <Positions positions={state.positions} />
    </div>
  );
}
