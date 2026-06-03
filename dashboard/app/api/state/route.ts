import { fetchAlgoState } from "@/lib/vps";

// Lightweight one-shot state read for client polling. This replaces the old SSE
// /api/stream route, which held a serverless function open for the ENTIRE time a
// dashboard tab was open — billing Fluid provisioned memory (and active CPU) for the
// whole session. A quick read-KV-and-return per poll is ~100× cheaper and scales to
// zero when no tab is open.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const state = await fetchAlgoState();
  return Response.json(state ?? null, { headers: { "Cache-Control": "no-store" } });
}
