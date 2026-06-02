// Live quotes for the watchlist: price + today's % change, from Yahoo (free, no key).
export const runtime = "nodejs";
export const revalidate = 20;

const SYMBOLS: Record<string, string> = {
  US500: "^GSPC", SPX: "^GSPC", NAS100: "^NDX", FTSE100: "^FTSE",
  DAX40: "^GDAXI", EURUSD: "EURUSD=X", GBPUSD: "GBPUSD=X",
};

async function quote(key: string) {
  const ysym = SYMBOLS[key] || key;
  try {
    const res = await fetch(
      `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ysym)}?interval=1d&range=2d`,
      { headers: { "User-Agent": "Mozilla/5.0" }, next: { revalidate: 20 } },
    );
    if (!res.ok) return { symbol: key, price: null, changePct: null };
    const j = await res.json();
    const meta = j?.chart?.result?.[0]?.meta;
    const price: number | null = meta?.regularMarketPrice ?? null;
    const prev: number | null = meta?.chartPreviousClose ?? meta?.previousClose ?? null;
    const changePct = price != null && prev ? ((price - prev) / prev) * 100 : null;
    return { symbol: key, price, changePct };
  } catch {
    return { symbol: key, price: null, changePct: null };
  }
}

export async function GET(request: Request) {
  const symbols = (new URL(request.url).searchParams.get("symbols") || "US500")
    .split(",").map((s) => s.trim().toUpperCase()).filter(Boolean).slice(0, 12);
  const quotes = await Promise.all(symbols.map(quote));
  return Response.json({ quotes });
}
