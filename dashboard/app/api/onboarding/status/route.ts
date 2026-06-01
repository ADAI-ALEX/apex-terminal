import { vpsFetch } from "@/lib/vps";
import { kvEnabled, kvGet, CONFIG_KEY, STATUS_KEY } from "@/lib/kv";

// Bootstrap gate the dashboard reads before it knows if the algo is configured.
// Cloud-relay mode reads KV; direct mode proxies the state server.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type StoredConfig = {
  ig?: { acc_type?: string; username?: string };
  anthropic?: { api_key?: string };
  risk?: { profile?: string; active_markets?: string[]; trading_enabled?: boolean };
  configured_at?: string;
};

export async function GET() {
  if (kvEnabled()) {
    // The algo writes an authoritative status once it picks up the config.
    const confirmed = await kvGet<Record<string, unknown>>(STATUS_KEY);
    if (confirmed) return Response.json(confirmed, { status: 200 });

    // Config saved but the algo hasn't connected yet → "pending".
    const cfg = await kvGet<StoredConfig>(CONFIG_KEY);
    if (cfg) {
      const hasIg = !!(cfg.ig?.username);
      return Response.json(
        {
          configured: true,
          mode: hasIg ? cfg.ig?.acc_type ?? "DEMO" : "PAPER",
          acc_type: cfg.ig?.acc_type ?? "DEMO",
          ig_connected: hasIg,
          claude_enabled: !!cfg.anthropic?.api_key,
          risk_profile: cfg.risk?.profile ?? "prop_ftmo",
          active_markets: cfg.risk?.active_markets ?? [],
          trading_enabled: !!cfg.risk?.trading_enabled,
          masked: {},
          configured_at: cfg.configured_at ?? null,
          awaiting_algo: true, // dashboard hint: saved, waiting for laptop to connect
        },
        { status: 200 },
      );
    }
    return Response.json({ configured: false, mode: "UNCONFIGURED", masked: {}, active_markets: [] });
  }

  const res = await vpsFetch("/onboarding/status");
  if (!res) {
    return Response.json(
      { configured: false, mode: "UNREACHABLE", masked: {}, active_markets: [] },
      { status: 200 },
    );
  }
  const data = await res.json();
  return Response.json(data, { status: res.status });
}
