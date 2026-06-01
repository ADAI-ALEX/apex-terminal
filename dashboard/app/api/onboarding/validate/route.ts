import { vpsFetch } from "@/lib/vps";

// Proxy → state server POST /onboarding/validate. Tests IG / Claude credentials
// live without persisting anything. The browser never sees X-Apex-Secret.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await request.text();
  const res = await vpsFetch("/onboarding/validate", { method: "POST", body });
  if (!res) {
    return Response.json(
      {
        ok: false,
        results: [
          { field: "ig", ok: false, detail: "Cannot reach the algo state server. Is it running?" },
        ],
      },
      { status: 200 },
    );
  }
  const data = await res.json();
  return Response.json(data, { status: res.status });
}
