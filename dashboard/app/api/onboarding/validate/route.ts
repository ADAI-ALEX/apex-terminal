import { vpsFetch } from "@/lib/vps";
import { kvEnabled } from "@/lib/kv";

// Test credentials. Direct mode runs a live IG/Claude check on the algo host. Cloud-
// relay mode can't reach the algo synchronously, so the real check happens when the
// laptop picks up the saved config — we report that here instead of a false failure.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await request.text();

  if (kvEnabled()) {
    return Response.json(
      {
        ok: true,
        results: [
          { field: "ig", ok: true, detail: "Will be verified by your algo when it picks up the config (after Activate)." },
          { field: "anthropic", ok: true, detail: "Will be verified by your algo on activation." },
        ],
      },
      { status: 200 },
    );
  }

  const res = await vpsFetch("/onboarding/validate", { method: "POST", body });
  if (!res) {
    return Response.json(
      { ok: false, results: [{ field: "ig", ok: false, detail: "Cannot reach the algo state server. Is it running?" }] },
      { status: 200 },
    );
  }
  const data = await res.json();
  return Response.json(data, { status: res.status });
}
