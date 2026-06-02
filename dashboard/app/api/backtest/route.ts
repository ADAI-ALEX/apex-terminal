import { vpsFetch } from "@/lib/vps";
import { kvEnabled, kvGet, kvSet, BACKTEST_REQ_KEY, BACKTEST_RES_KEY } from "@/lib/kv";

// Backtest relay. Cloud mode: POST queues a request in KV (the laptop runs it and
// writes the result), GET polls the result. Local mode: POST runs synchronously on
// the state server.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: Request) {
  const params = await request.json().catch(() => ({}));

  if (kvEnabled()) {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    await kvSet(BACKTEST_REQ_KEY, { id, ...params });
    return Response.json({ id, queued: true });
  }

  // Local mode → run synchronously on the state server.
  const res = await vpsFetch("/backtest", { method: "POST", body: JSON.stringify(params) });
  if (!res) return Response.json({ error: "Cannot reach the algo state server." }, { status: 200 });
  const data = await res.json();
  return Response.json(data, { status: res.status });
}

export async function GET(request: Request) {
  if (!kvEnabled()) return Response.json({ error: "Use POST in local mode." }, { status: 200 });
  const id = new URL(request.url).searchParams.get("id");
  const result = await kvGet<Record<string, unknown>>(BACKTEST_RES_KEY);
  if (result && (!id || result.id === id)) return Response.json(result);
  return Response.json({ pending: true });
}
