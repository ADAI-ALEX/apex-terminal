import { vpsFetch } from "@/lib/vps";

// Proxy → state server GET /onboarding/status. No secrets in the body; this is the
// bootstrap gate the dashboard reads before it knows whether the algo is configured.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
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
