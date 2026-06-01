import { vpsFetch } from "@/lib/vps";
import { kvEnabled, kvGet, CONFIG_KEY, STATUS_KEY } from "@/lib/kv";

// Bootstrap gate the dashboard reads before it knows if the algo is configured.
// Cloud-relay mode reads KV; direct mode proxies the state server.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type StoredConfig = {
  ig?: { acc_type?: string; username?: string };
  anthropic?: { api_key?: string; model?: string };
  risk?: {
    profile?: string;
    active_markets?: string[];
    trading_enabled?: boolean;
    starting_equity?: number;
    account_currency?: string;
    daily_target_pct?: number;
  };
  configured_at?: string;
};

export async function GET() {
  if (kvEnabled()) {
    // SOURCE OF TRUTH = the config key. A stale status key must never make the gate
    // think we're configured when the config is actually gone (that caused a deadlock:
    // dashboard showed "configured" while the engine saw nothing).
    const cfg = await kvGet<StoredConfig>(CONFIG_KEY);
    if (!cfg || (!cfg.ig?.username && !cfg.risk?.profile)) {
      return Response.json({ configured: false, mode: "UNCONFIGURED", masked: {}, active_markets: [] });
    }

    // Config exists → configured. Enrich with the algo's confirmed status if present.
    const confirmed = await kvGet<Record<string, unknown>>(STATUS_KEY);
    const hasIg = !!cfg.ig?.username;
    const mode =
      confirmed && typeof confirmed.mode === "string"
        ? (confirmed.mode as string)
        : hasIg
          ? cfg.ig?.acc_type ?? "DEMO"
          : "PAPER";
    return Response.json(
      {
        configured: true,
        mode,
        acc_type: cfg.ig?.acc_type ?? "DEMO",
        ig_connected: hasIg,
        claude_enabled: !!cfg.anthropic?.api_key,
        claude_model: cfg.anthropic?.model ?? "claude-sonnet-4-6",
        risk_profile: cfg.risk?.profile ?? "prop_ftmo",
        active_markets: cfg.risk?.active_markets ?? [],
        starting_equity: cfg.risk?.starting_equity ?? 0,
        account_currency: cfg.risk?.account_currency ?? "GBP",
        trading_enabled: !!cfg.risk?.trading_enabled,
        masked: {},
        configured_at: cfg.configured_at ?? null,
        awaiting_algo: !confirmed, // saved, but the engine hasn't confirmed yet
      },
      { status: 200 },
    );
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
