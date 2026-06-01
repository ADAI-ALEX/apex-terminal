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
