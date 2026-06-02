// Minimal Upstash/Vercel-KV REST client (no SDK — uses fetch). Accepts either the
// Vercel-injected KV_REST_API_* names or the native UPSTASH_REDIS_REST_* names, so it
// works whichever Redis integration you attach. Values are JSON strings, matching
// apex/cloud/kv.py exactly (laptop and dashboard share the same keys).

export const CONFIG_KEY = "apex:config";
export const STATE_KEY = "apex:state";
export const STATUS_KEY = "apex:onboarding_status";
export const BACKTEST_REQ_KEY = "apex:backtest_request";
export const BACKTEST_RES_KEY = "apex:backtest_result";

function creds(): { url: string; token: string } | null {
  const url = process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!url || !token) return null;
  return { url: url.replace(/\/$/, ""), token };
}

/** Cloud-relay mode is active whenever Redis REST credentials are present. */
export function kvEnabled(): boolean {
  return creds() !== null;
}

export async function kvGet<T>(key: string): Promise<T | null> {
  const c = creds();
  if (!c) return null;
  try {
    const res = await fetch(`${c.url}/get/${key}`, {
      headers: { Authorization: `Bearer ${c.token}` },
      cache: "no-store",
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { result: string | null };
    if (body.result == null || body.result === "") return null;
    return JSON.parse(body.result) as T;
  } catch {
    return null;
  }
}

export async function kvSet(key: string, value: unknown): Promise<boolean> {
  const c = creds();
  if (!c) return false;
  try {
    const res = await fetch(`${c.url}/set/${key}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${c.token}` },
      body: JSON.stringify(value),
      cache: "no-store",
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function kvDel(key: string): Promise<boolean> {
  const c = creds();
  if (!c) return false;
  try {
    const res = await fetch(`${c.url}/del/${key}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${c.token}` },
      cache: "no-store",
    });
    return res.ok;
  } catch {
    return false;
  }
}
