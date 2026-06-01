import { vpsFetch } from "@/lib/vps";
import { kvEnabled, kvSet, kvDel, CONFIG_KEY, STATUS_KEY } from "@/lib/kv";

// Persist onboarding config. Cloud-relay mode writes it to KV (the laptop algo picks
// it up and validates on its next poll); direct mode validates + saves on the server.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await request.text();

  if (kvEnabled()) {
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(body);
    } catch {
      return Response.json({ ok: false, results: [{ field: "ig", ok: false, detail: "Invalid request." }] }, { status: 400 });
    }
    const record = { ...payload, configured_at: new Date().toISOString() };
    const ok = await kvSet(CONFIG_KEY, record);
    await kvDel(STATUS_KEY); // clear any stale algo confirmation
    if (!ok) {
      return Response.json(
        { ok: false, results: [{ field: "ig", ok: false, detail: "Could not write config to Vercel KV." }] },
        { status: 502 },
      );
    }
    return Response.json({ ok: true, results: [] }, { status: 200 });
  }

  const res = await vpsFetch("/onboarding/save", { method: "POST", body });
  if (!res) {
    return Response.json(
      { ok: false, results: [{ field: "ig", ok: false, detail: "Cannot reach the algo state server. Is it running?" }] },
      { status: 200 },
    );
  }
  const data = await res.json();
  return Response.json(data, { status: res.status });
}
