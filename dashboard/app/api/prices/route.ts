// Free, fast, no-key candle source for the chart — proxies Yahoo Finance's chart API
// server-side (avoids CORS), normalises to OHLC, and caches briefly. Decoupled from
// the trading engine: the chart loads instantly even before the laptop streams data.
export const runtime = "nodejs";
export const revalidate = 30;

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
  "1m": "5d", "5m": "1mo", "15m": "1mo", "30m": "3mo", "60m": "6mo", "1d": "5y",
};

export async function GET(request: Request) {
  const url = new URL(request.url);
  const key = (url.searchParams.get("symbol") || "US500").toUpperCase();
  let interval = url.searchParams.get("interval") || "15m";
  if (interval === "1h") interval = "60m";
  const range = url.searchParams.get("range") || RANGE_FOR[interval] || "1mo";
  const ysym = SYMBOLS[key] || url.searchParams.get("symbol") || "^GSPC";

  const endpoint = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ysym)}?interval=${interval}&range=${range}`;
  try {
    const res = await fetch(endpoint, {
      headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" },
      next: { revalidate: 30 },
    });
    if (!res.ok) return Response.json({ candles: [], error: `upstream ${res.status}` });
    const j = await res.json();
    const r = j?.chart?.result?.[0];
    const ts: number[] = r?.timestamp ?? [];
    const q = r?.indicators?.quote?.[0] ?? {};
    const candles = ts
      .map((t, i) => ({ time: t, open: q.open?.[i], high: q.high?.[i], low: q.low?.[i], close: q.close?.[i] }))
      .filter((c) => c.open != null && c.high != null && c.low != null && c.close != null);
    return Response.json({ symbol: key, ysym, interval, range, candles });
  } catch (e) {
    return Response.json({ candles: [], error: String(e) });
  }
}
