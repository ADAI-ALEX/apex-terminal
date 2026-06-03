// Candle source for the chart, with pagination for lazy history loading.
//   ?symbol=US500&interval=15m[&before=<unixSecs>][&limit=250]
// Returns the newest `limit` bars (or the `limit` bars just before `before`) plus a
// `hasMore` flag so the client can keep fetching older data as the user scrolls back.
// Order of preference:
//   1) Engine-published candles in KV (apex:chart:<sym>:<iv>) — fetched from the LAPTOP's
//      Yahoo access, which works; Vercel's serverless IP is routinely blocked by Yahoo.
//   2) Direct Yahoo (works on residential IPs / local dev).
//   3) The live engine snapshot's single-interval candles (apex:state) as a last resort.
import { kvEnabled, kvGet, CHART_KEY, STATE_KEY } from "@/lib/kv";

export const runtime = "nodejs";
export const revalidate = 30;

type Candle = { time: number; open: number; high: number; low: number; close: number };

const SYMBOLS: Record<string, string> = {
  US500: "^GSPC", SPX: "^GSPC", NAS100: "^NDX", FTSE100: "^FTSE",
  DAX40: "^GDAXI", EURUSD: "EURUSD=X", GBPUSD: "GBPUSD=X",
};

const RANGE_FOR: Record<string, string> = {
  "1m": "5d", "5m": "1mo", "15m": "1mo", "30m": "1mo", "60m": "2y", "1d": "10y",
};

export async function GET(request: Request) {
  const url = new URL(request.url);
  const key = (url.searchParams.get("symbol") || "US500").toUpperCase();
  const reqInterval = url.searchParams.get("interval") || "15m"; // as the chart sends it (5m/15m/1h/1d)
  const limit = Math.min(500, Math.max(40, Number(url.searchParams.get("limit")) || 250));
  const before = Math.floor(Number(url.searchParams.get("before")) || 0); // unix secs; 0 = newest

  // Slice a deep, ascending series into the requested page + report whether older bars remain.
  const page = (all: Candle[]) => {
    const arr = before ? all.filter((c) => c.time < before) : all;
    const chunk = arr.slice(-limit);
    return { chunk, hasMore: arr.length > chunk.length };
  };
  const ok = (candles: Candle[], hasMore: boolean, source: string) =>
    Response.json({ symbol: key, interval: reqInterval, candles, hasMore, source });

  // 1) Engine-published chart candles (reliable on Vercel — fetched from the laptop).
  if (kvEnabled()) {
    const rows = await kvGet<Candle[]>(`${CHART_KEY}:${key}:${reqInterval}`);
    if (rows && rows.length) { const { chunk, hasMore } = page(rows); return ok(chunk, hasMore, "engine"); }
    const blob = await kvGet<Record<string, Record<string, Candle[]>>>(CHART_KEY);
    const legacy = blob?.[key]?.[reqInterval];
    if (legacy && legacy.length) { const { chunk, hasMore } = page(legacy); return ok(chunk, hasMore, "engine-blob"); }
  }

  // 2) Direct Yahoo (free, no key) — works locally and from non-blocked IPs.
  let interval = reqInterval;
  if (interval === "1h") interval = "60m";
  const range = url.searchParams.get("range") || RANGE_FOR[interval] || "1mo";
  const ysym = SYMBOLS[key] || url.searchParams.get("symbol") || "^GSPC";
  const endpoint = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ysym)}?interval=${interval}&range=${range}`;
  try {
    const res = await fetch(endpoint, {
      headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" },
      next: { revalidate: 30 },
    });
    if (res.ok) {
      const j = await res.json();
      const r = j?.chart?.result?.[0];
      const ts: number[] = r?.timestamp ?? [];
      const q = r?.indicators?.quote?.[0] ?? {};
      const candles: Candle[] = ts
        .map((t, i) => ({ time: t, open: q.open?.[i], high: q.high?.[i], low: q.low?.[i], close: q.close?.[i] }))
        .filter((c) => c.open != null && c.high != null && c.low != null && c.close != null);
      if (candles.length) { const { chunk, hasMore } = page(candles); return ok(chunk, hasMore, "yahoo"); }
    }
  } catch {
    /* fall through to the snapshot fallback */
  }

  // 3) Last resort: the live engine snapshot's candles (single interval) from KV.
  if (kvEnabled()) {
    const st = await kvGet<{ candles?: Record<string, Candle[]> }>(STATE_KEY);
    const fb = st?.candles?.[key];
    if (fb && fb.length) { const { chunk, hasMore } = page(fb); return ok(chunk, hasMore, "state"); }
  }

  return Response.json({ symbol: key, interval: reqInterval, candles: [], hasMore: false, error: "no data" });
}
