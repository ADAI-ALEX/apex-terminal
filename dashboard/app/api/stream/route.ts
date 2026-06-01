import { fetchAlgoState } from "@/lib/vps";

// SSE endpoint. Polls the VPS state server every ~3s and streams to the browser.
// Vercel has no persistent WebSockets — SSE over a Node function is the pattern.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// The engine pushes state to KV ~every 30s, so polling faster just wastes reads.
const POLL_MS = 15000;

export async function GET(request: Request) {
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      let closed = false;
      let timer: ReturnType<typeof setInterval> | undefined;
      const close = () => {
        if (closed) return;
        closed = true;
        if (timer) clearInterval(timer);
        try {
          controller.close();
        } catch {
          /* already closed */
        }
      };

      const send = (event: string, data: unknown) => {
        if (closed) return;
        controller.enqueue(
          encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`),
        );
      };

      const tick = async () => {
        const state = await fetchAlgoState();
        if (state) send("state", state);
        else send("error", { message: "VPS unreachable" });
      };

      request.signal.addEventListener("abort", close);
      await tick();
      timer = setInterval(tick, POLL_MS);
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
