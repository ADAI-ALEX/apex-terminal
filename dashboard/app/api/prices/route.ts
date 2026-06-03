// Candle source for the chart. Order of preference:
//   1) Engine-published candles in KV (apex:chart) — fetched from the LAPTOP's Yahoo
//      access, which works; Vercel's serverless IP is routinely blocked by Yahoo.
//   2) Direct Yahoo (works on residential IPs / local dev).
//   3) The live engine snapshot's single-interval candles (apex:state) as a last resort.
import { kvEnabled, kvGet, CHART_KEY, STATE_KEY } from "@/lib/kv";

export const runtime = "nodejs";
export const revalidate = 30;

type Candle = { time: number; open: number; high: number; low: number; close: number };

// Our instrument keys → Yahoo symbols (indices use the cash index; FX uses =X pairs).
const SYMBOLS: Record<string, string> = {
  US500: "^GSPC",
  SPX: "^GSPC",
  NAS100: "^NDX",
  FTSE100: "^FTSE",
  DAX40: "^GDAXI",
  EURUSD: "EURUSD=X",
  GBPUSD: "GBPUSD=X",
};

// Yahoo only serves intraday for limited windows — pick a sensible range per interval.
const RANGE_FOR: Record<string, string> = {
  "1m": "5d", "5m": "1mo", "15m": "1mo", "30m": "1mo", "60m": "2y", "1d": "10y",
};

export async function GET(request: Request) {
  const url = new URL(request.url);
  const key = (url.searchParams.get("symbol") || "US500").toUpperCase();
  const reqInterval = url.searchParams.get("interval") || "15m"; // as the chart sends it (5m/15m/1h/1d)

  // 1) Engine-published chart candles (reliable on Vercel — fetched from the laptop).
  if (kvEnabled()) {
    const chart = await kvGet<Record<string, Record<string, Candle[]>>>(CHART_KEY);
    const rows = chart?.[key]?.[reqInterval];
    if (rows && rows.length) {
      return Response.json({ symbol: key, interval: reqInterval, candles: rows, source: "engine" });
    }
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
      const candles = ts
        .map((t, i) => ({ time: t, open: q.open?.[i], high: q.high?.[i], low: q.low?.[i], close: q.close?.[i] }))
        .filter((c) => c.open != null && c.high != null && c.low != null && c.close != null);
      if (candles.length) return Response.json({ symbol: key, ysym, interval, range, candles, source: "yahoo" });
    }
  } catch {
    /* fall through to the snapshot fallback */
  }

  // 3) Last resort: the live engine snapshot's candles (single interval) from KV.
  if (kvEnabled()) {
    const st = await kvGet<{ candles?: Record<string, Candle[]> }>(STATE_KEY);
    const fb = st?.candles?.[key];
    if (fb && fb.length) return Response.json({ symbol: key, candles: fb, source: "state" });
  }

  return Response.json({ candles: [], error: "no data" });
}
