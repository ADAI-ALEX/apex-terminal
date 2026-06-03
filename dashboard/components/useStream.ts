"use client";

import { useEffect, useState } from "react";
import type { AlgoState } from "@/lib/types";

export type StreamStatus = "connecting" | "live" | "error";

// The engine pushes state to KV ~every 30s, so polling every 15s is plenty.
const POLL_MS = 15000;

/**
 * Poll /api/state for the latest AlgoState.
 *
 * Previously this used an SSE connection (/api/stream) that held a Vercel function open
 * for the whole session — expensive on Fluid Compute (provisioned memory billed for the
 * connection lifetime). Short polling keeps each request ~100ms and lets the platform
 * scale to zero between polls. Polling pauses while the tab is hidden.
 */
export function useStream(): { state: AlgoState | null; status: StreamStatus } {
  const [state, setState] = useState<AlgoState | null>(null);
  const [status, setStatus] = useState<StreamStatus>("connecting");

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;

    const schedule = () => { timer = setTimeout(poll, POLL_MS); };

    const poll = async () => {
      if (stopped) return;
      // Don't burn requests (or function time) while the tab is in the background.
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        schedule();
        return;
      }
      try {
        const res = await fetch("/api/state", { cache: "no-store" });
        const data = (await res.json()) as AlgoState | null;
        if (stopped) return;
        if (data) { setState(data); setStatus("live"); }
        else setStatus("error");
      } catch {
        if (!stopped) setStatus("error");
      } finally {
        if (!stopped) schedule();
      }
    };

    const onVisible = () => {
      if (document.visibilityState === "visible") { clearTimeout(timer); void poll(); }
    };

    document.addEventListener("visibilitychange", onVisible);
    void poll();
    return () => { stopped = true; clearTimeout(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, []);

  return { state, status };
}
