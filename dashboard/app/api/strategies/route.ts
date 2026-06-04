import { vpsFetch } from "@/lib/vps";
import {
  kvEnabled, kvGet, kvSet, STRATEGIES_KEY, STRATEGY_WRITE_KEY, STRATEGY_WRITE_ACK_KEY,
} from "@/lib/kv";

// Strategy library relay. Mirrors /api/backtest:
//   • Cloud mode (KV present): GET reads the laptop-published strategy list;
//     POST queues a save/delete that the laptop persists to disk.
//   • Local mode: proxy the state server's /strategies endpoints directly.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type Strategy = {
  name: string; label: string; description: string;
  kind: "builtin" | "default" | "custom"; editable: boolean; code: string;
};

// Always-available built-in so the dropdown is never empty (laptop offline, etc.).
const BUILTIN_FALLBACK: Strategy[] = [
  {
    name: "book", label: "Strategy Book (built-in)",
    description: "The live multi-strategy book: EMA-trend, RSI-reversion and ATR-breakout, gated by the regime detector.",
    kind: "builtin", editable: false, code: "",
  },
];

export async function GET() {
  if (kvEnabled()) {
    const list = await kvGet<Strategy[]>(STRATEGIES_KEY);
    const strategies = Array.isArray(list) && list.length ? list : BUILTIN_FALLBACK;
    return Response.json({ strategies, source: "kv" });
  }
  const res = await vpsFetch("/strategies");
  if (!res || !res.ok) return Response.json({ strategies: BUILTIN_FALLBACK, source: "none" });
  try {
    const data = (await res.json()) as { strategies?: Strategy[] };
    return Response.json({ strategies: data.strategies ?? BUILTIN_FALLBACK, source: "vps" });
  } catch {
    return Response.json({ strategies: BUILTIN_FALLBACK, source: "none" });
  }
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as {
    action?: "save" | "delete"; name?: string; code?: string;
  };
  const action = body.action ?? "save";
  const name = (body.name ?? "").trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,48}$/.test(name)) {
    return Response.json({ ok: false, error: "Invalid strategy name." }, { status: 200 });
  }

  if (kvEnabled()) {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    await kvSet(STRATEGY_WRITE_KEY, { id, action, name, code: body.code ?? "" });
    // Best-effort: briefly poll for the laptop's ack so the UI can confirm the save.
    for (let i = 0; i < 6; i++) {
      await new Promise((r) => setTimeout(r, 500));
      const ack = await kvGet<{ id: string; ok: boolean; error?: string }>(STRATEGY_WRITE_ACK_KEY);
      if (ack && ack.id === id) return Response.json({ ...ack, queued: true });
    }
    return Response.json({ ok: true, queued: true, id, pending: true });
  }

  const res = await vpsFetch("/strategies", { method: "POST", body: JSON.stringify({ action, name, code: body.code ?? "" }) });
  if (!res) return Response.json({ ok: false, error: "Cannot reach the algo state server." }, { status: 200 });
  const data = await res.json().catch(() => ({ ok: false, error: "Bad response from state server." }));
  return Response.json(data, { status: 200 });
}
