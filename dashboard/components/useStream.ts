"use client";

import { useEffect, useState } from "react";
import type { AlgoState } from "@/lib/types";

export type StreamStatus = "connecting" | "live" | "error";

/**
 * Subscribe to the /api/stream SSE endpoint and return the latest AlgoState.
 * Reconnects automatically if the stream drops.
 */
export function useStream(): { state: AlgoState | null; status: StreamStatus } {
  const [state, setState] = useState<AlgoState | null>(null);
  const [status, setStatus] = useState<StreamStatus>("connecting");

  useEffect(() => {
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout>;

    const disconnect = () => {
      source?.close();
      source = null;
      clearTimeout(retry);
    };

    const connect = () => {
      // Only stream while the tab is visible — saves KV reads / bandwidth when
      // the dashboard is in the background or another tab.
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      if (source) return;
      setStatus("connecting");
      source = new EventSource("/api/stream");

      source.addEventListener("state", (e) => {
        try {
          setState(JSON.parse((e as MessageEvent).data) as AlgoState);
          setStatus("live");
        } catch {
          /* ignore malformed frame */
        }
      });

      source.addEventListener("error", () => {
        setStatus("error");
        disconnect();
        retry = setTimeout(connect, 5000);
      });
    };

    const onVisibility = () => {
      if (document.visibilityState === "visible") connect();
      else disconnect();
    };

    document.addEventListener("visibilitychange", onVisibility);
    connect();
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      disconnect();
    };
  }, []);

  return { state, status };
}
