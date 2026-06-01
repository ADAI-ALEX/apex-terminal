import { vpsFetch } from "@/lib/vps";
import { kvEnabled, kvGet, kvSet, CONFIG_KEY } from "@/lib/kv";

// Merge a partial config update from the Settings page. Cloud-relay mode merges into
// the KV config (the laptop picks it up within ~20s); direct mode proxies the algo.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type Section = Record<string, unknown>;
type StoredConfig = { ig?: Section; anthropic?: Section; risk?: Section; configured_at?: string };

function mergeSection(current: Section, incoming: Section): Section {
  const out = { ...current };
  for (const [k, v] of Object.entries(incoming)) {
    // Never clobber a stored secret with a blank value.
    if ((k === "password" || k === "api_key") && (v === "" || v == null)) continue;
    out[k] = v;
  }
  return out;
}

export async function POST(request: Request) {
  let update: StoredConfig;
  try {
    update = (await request.json()) as StoredConfig;
  } catch {
    return Response.json({ ok: false }, { status: 400 });
  }

  if (kvEnabled()) {
    const cur = (await kvGet<StoredConfig>(CONFIG_KEY)) ?? { ig: {}, anthropic: {}, risk: {} };
    const merged: StoredConfig = {
      ig: mergeSection(cur.ig ?? {}, update.ig ?? {}),
      anthropic: mergeSection(cur.anthropic ?? {}, update.anthropic ?? {}),
      risk: mergeSection(cur.risk ?? {}, update.risk ?? {}),
      configured_at: new Date().toISOString(), // bump so the laptop detects the change
    };
    const ok = await kvSet(CONFIG_KEY, merged);
    return Response.json({ ok }, { status: ok ? 200 : 502 });
  }

  // Direct mode → state server merge endpoint.
  const res = await vpsFetch("/onboarding/update", { method: "POST", body: JSON.stringify(update) });
  if (!res) return Response.json({ ok: false }, { status: 200 });
  return Response.json({ ok: res.ok }, { status: res.status });
}
