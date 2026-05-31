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

    const connect = () => {
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
        source?.close();
        retry = setTimeout(connect, 4000);
      });
    };

    connect();
    return () => {
      source?.close();
      clearTimeout(retry);
    };
  }, []);

  return { state, status };
}
