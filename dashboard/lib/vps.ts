import type { AlgoState } from "./types";
import { kvEnabled, kvGet, STATE_KEY } from "./kv";

/**
 * Server-side proxy to the VPS FastAPI state server. Keeps VPS_SECRET on the
 * server (never shipped to the browser). Returns null if the VPS is unreachable
 * or unconfigured. Used by the SSE stream and the onboarding API routes.
 */
export async function vpsFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response | null> {
  const url = process.env.VPS_URL;
  const secret = process.env.VPS_SECRET;
  if (!url || !secret) return null;

  const headers = new Headers(init.headers);
  headers.set("X-Apex-Secret", secret);
  if (init.body) headers.set("Content-Type", "application/json");

  try {
    return await fetch(`${url}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    return null;
  }
}

/**
 * Fetch the current algo state from the VPS FastAPI server.
 * Sends the shared secret; only our deployment can read /state.
 */
export async function fetchAlgoState(): Promise<AlgoState | null> {
  // Cloud-relay mode: the laptop pushes state to KV; read it from there.
  if (kvEnabled()) {
    return await kvGet<AlgoState>(STATE_KEY);
  }
  // Direct mode: proxy the VPS/local state server.
  const res = await vpsFetch("/state");
  if (!res || !res.ok) return null;
  try {
    return (await res.json()) as AlgoState;
  } catch {
    return null;
  }
}
