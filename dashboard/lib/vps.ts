import type { AlgoState } from "./types";

/**
 * Fetch the current algo state from the VPS FastAPI server.
 * Sends the shared secret; only our deployment can read /state.
 */
export async function fetchAlgoState(): Promise<AlgoState | null> {
  const url = process.env.VPS_URL;
  const secret = process.env.VPS_SECRET;
  if (!url || !secret) return null;

  try {
    const res = await fetch(`${url}/state`, {
      headers: { "X-Apex-Secret": secret },
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as AlgoState;
  } catch {
    return null;
  }
}
