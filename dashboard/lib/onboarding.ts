// Client-side onboarding types + fetchers. These call the Next.js /api/onboarding/*
// proxy routes (server-side), which add the X-Apex-Secret and forward to the VPS.
// Mirrors apex/onboarding/schema.py.

export interface OnboardingStatus {
  configured: boolean;
  ig_connected: boolean;
  claude_enabled: boolean;
  claude_model: string;
  mode: string; // UNCONFIGURED | PAPER | DEMO | LIVE | UNREACHABLE
  acc_type: string;
  risk_profile: string;
  active_markets: string[];
  starting_equity: number;
  account_currency: string;
  trading_enabled: boolean;
  masked: Record<string, string>;
  configured_at: string | null;
}

// Partial update from the Settings page. Blank secrets are preserved server-side.
export interface SettingsUpdate {
  ig?: Partial<{ acc_type: string; username: string; password: string; api_key: string; account_id: string }>;
  anthropic?: Partial<{ api_key: string; model: string }>;
  risk?: Partial<{
    profile: string;
    active_markets: string[];
    trading_enabled: boolean;
    starting_equity: number;
    account_currency: string;
    daily_target_pct: number;
  }>;
}

export async function saveSettings(update: SettingsUpdate): Promise<{ ok: boolean }> {
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    });
    return { ok: res.ok };
  } catch {
    return { ok: false };
  }
}

export interface FieldValidation {
  field: string;
  ok: boolean;
  detail: string;
}

export interface ValidationResponse {
  ok: boolean;
  results: FieldValidation[];
}

export interface OnboardingPayload {
  ig: {
    acc_type: string;
    username: string;
    password: string;
    api_key: string;
    account_id: string;
  };
  anthropic: { api_key: string; model: string };
  risk: {
    profile: string;
    starting_equity: number;
    account_currency: string;
    active_markets: string[];
    daily_target_pct: number;
    trading_enabled: boolean;
  };
}

export async function getOnboardingStatus(): Promise<OnboardingStatus | null> {
  try {
    const res = await fetch("/api/onboarding/status", { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as OnboardingStatus;
  } catch {
    return null;
  }
}

export async function validateOnboarding(
  payload: OnboardingPayload,
): Promise<ValidationResponse> {
  const res = await fetch("/api/onboarding/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return (await res.json()) as ValidationResponse;
}

export async function saveOnboarding(
  payload: OnboardingPayload,
): Promise<ValidationResponse> {
  const res = await fetch("/api/onboarding/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  // Both 200 (ok) and 422 (validation failed) return a ValidationResponse-shaped body.
  const data = await res.json();
  return (data.detail ?? data) as ValidationResponse;
}
