"use client";

import { useMemo, useState } from "react";
import {
  saveOnboarding,
  validateOnboarding,
  type FieldValidation,
  type OnboardingPayload,
} from "@/lib/onboarding";

// Client mirror of the headline numbers in apex/config.py RISK_PROFILES — for the
// summary panel only. The server is the source of truth.
const PROFILES: Record<string, { label: string; perTrade: string; daily: string; total: string }> = {
  prop_ftmo: {
    label: "Prop Firm — Conservative (recommended)",
    perTrade: "0.4% / trade",
    daily: "−3% daily (breaker at −2.5%)",
    total: "−8% total (breaker at −7.5%)",
  },
  ig_standard: {
    label: "IG Standard",
    perTrade: "2% / trade",
    daily: "−5% daily",
    total: "−10% weekly halt",
  },
};

const ALL_MARKETS = ["US500", "NAS100", "EURUSD", "GBPUSD", "FTSE100", "DAX40"];

const EMPTY: OnboardingPayload = {
  ig: { acc_type: "DEMO", username: "", password: "", api_key: "", account_id: "" },
  anthropic: { api_key: "", model: "claude-sonnet-4-6" },
  risk: {
    profile: "prop_ftmo",
    starting_equity: 100000,
    account_currency: "GBP",
    active_markets: ["US500", "EURUSD"],
    daily_target_pct: 0.5,
    trading_enabled: false,
  },
};

const STEPS = ["Broker", "Claude AI", "Risk profile", "Review & activate"];

export function OnboardingWizard({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState(0);
  const [p, setP] = useState<OnboardingPayload>(EMPTY);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<FieldValidation | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string>("");

  const profile = PROFILES[p.risk.profile] ?? PROFILES.prop_ftmo;

  function patchIg(v: Partial<OnboardingPayload["ig"]>) {
    setP((s) => ({ ...s, ig: { ...s.ig, ...v } }));
    setResult(null);
  }
  function patchAnth(v: Partial<OnboardingPayload["anthropic"]>) {
    setP((s) => ({ ...s, anthropic: { ...s.anthropic, ...v } }));
    setResult(null);
  }
  function patchRisk(v: Partial<OnboardingPayload["risk"]>) {
    setP((s) => ({ ...s, risk: { ...s.risk, ...v } }));
  }

  async function test(field: "ig" | "anthropic") {
    setTesting(true);
    setResult(null);
    const res = await validateOnboarding(p);
    setTesting(false);
    setResult(res.results.find((r) => r.field === field) ?? null);
  }

  async function activate() {
    setSaving(true);
    setSaveError("");
    const res = await saveOnboarding(p);
    setSaving(false);
    if (res.ok) {
      onComplete();
      return;
    }
    setSaveError(
      res.results?.map((r) => `${r.field}: ${r.detail}`).join("  ·  ") ||
        "Activation failed — check your credentials.",
    );
  }

  function toggleMarket(m: string) {
    const has = p.risk.active_markets.includes(m);
    patchRisk({
      active_markets: has
        ? p.risk.active_markets.filter((x) => x !== m)
        : [...p.risk.active_markets, m],
    });
  }

  return (
    <div className="mx-auto max-w-2xl rounded-md border border-border bg-bg2 p-6 sm:p-8">
      <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.3em] text-gold">
        ADAI Systems · Onboarding
      </div>
      <h2 className="mb-1 text-xl font-bold">Configure Apex Algo</h2>
      <p className="mb-6 text-sm text-textmid">
        No keys are stored in this browser. Credentials are validated against the live
        broker and saved <span className="text-gold">encrypted at rest</span> on the
        algo server. Trading stays locked until you activate below.
      </p>

      <Stepper step={step} />

      <div className="mt-6 space-y-4">
        {step === 0 && (
          <>
            <SelectField
              label="Account type"
              value={p.ig.acc_type}
              onChange={(v) => patchIg({ acc_type: v })}
              options={[
                ["DEMO", "Demo (recommended for testing)"],
                ["LIVE", "Live (real money)"],
              ]}
            />
            <Field label="IG username" value={p.ig.username} onChange={(v) => patchIg({ username: v })} />
            <Field label="IG password" type="password" value={p.ig.password} onChange={(v) => patchIg({ password: v })} />
            <Field label="IG API key" type="password" value={p.ig.api_key} onChange={(v) => patchIg({ api_key: v })} />
            <Field label="Account ID (optional)" value={p.ig.account_id} onChange={(v) => patchIg({ account_id: v })} />
            <p className="text-xs text-textdim">
              Leave blank to run in PAPER (simulation) mode with no broker connection.
            </p>
            <TestRow testing={testing} result={result} onTest={() => test("ig")} label="Test IG connection" />
          </>
        )}

        {step === 1 && (
          <>
            <Field label="Anthropic API key (optional)" type="password" value={p.anthropic.api_key} onChange={(v) => patchAnth({ api_key: v })} placeholder="sk-ant-…" />
            <Field label="Claude model" value={p.anthropic.model} onChange={(v) => patchAnth({ model: v })} />
            <p className="text-xs text-textdim">
              Powers signal evaluation. Without a key the algo runs on safe NO_TRADE
              defaults — Python still executes and protects every order.
            </p>
            <TestRow testing={testing} result={result} onTest={() => test("anthropic")} label="Test Claude key" />
          </>
        )}

        {step === 2 && (
          <>
            <SelectField
              label="Risk profile"
              value={p.risk.profile}
              onChange={(v) => patchRisk({ profile: v })}
              options={Object.entries(PROFILES).map(([k, v]) => [k, v.label])}
            />
            <div className="grid grid-cols-2 gap-3">
              <NumberField label="Starting equity" value={p.risk.starting_equity} onChange={(v) => patchRisk({ starting_equity: v })} />
              <SelectField
                label="Currency"
                value={p.risk.account_currency}
                onChange={(v) => patchRisk({ account_currency: v })}
                options={[["GBP", "GBP £"], ["USD", "USD $"], ["EUR", "EUR €"]]}
              />
            </div>
            <NumberField label="Daily target %" step={0.1} value={p.risk.daily_target_pct} onChange={(v) => patchRisk({ daily_target_pct: v })} />
            <div>
              <Label>Instruments</Label>
              <div className="mt-1 flex flex-wrap gap-2">
                {ALL_MARKETS.map((m) => {
                  const on = p.risk.active_markets.includes(m);
                  return (
                    <button
                      key={m}
                      type="button"
                      onClick={() => toggleMarket(m)}
                      className={`rounded border px-3 py-1.5 font-mono text-xs transition ${
                        on ? "border-gold bg-gold/10 text-gold" : "border-border text-textmid hover:border-gold/50"
                      }`}
                    >
                      {m}
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="rounded border border-border bg-bg3 p-3 font-mono text-[11px] text-textmid">
              <div>per-trade risk: <span className="text-gold">{profile.perTrade}</span></div>
              <div>daily guard: <span className="text-gold">{profile.daily}</span></div>
              <div>total guard: <span className="text-gold">{profile.total}</span></div>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <Review label="Account" value={`${p.ig.acc_type}${p.ig.username ? ` · ${p.ig.username}` : " · PAPER mode"}`} />
            <Review label="Claude" value={p.anthropic.api_key ? `enabled · ${p.anthropic.model}` : "disabled (safe defaults)"} />
            <Review label="Profile" value={profile.label} />
            <Review label="Equity" value={`${p.risk.starting_equity.toLocaleString()} ${p.risk.account_currency}`} />
            <Review label="Markets" value={p.risk.active_markets.join(", ") || "—"} />
            <label className="mt-2 flex items-center gap-3 rounded border border-border bg-bg3 p-3">
              <input
                type="checkbox"
                checked={p.risk.trading_enabled}
                onChange={(e) => patchRisk({ trading_enabled: e.target.checked })}
                className="h-4 w-4 accent-gold"
              />
              <span className="text-sm">
                Enable live order placement now
                <span className="block text-xs text-textdim">
                  Leave off to start monitoring-only; you can flip it later.
                </span>
              </span>
            </label>
            {saveError && <p className="text-sm text-down">{saveError}</p>}
          </>
        )}
      </div>

      <div className="mt-8 flex items-center justify-between">
        <button
          type="button"
          disabled={step === 0 || saving}
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          className="rounded border border-border px-4 py-2 font-mono text-[11px] uppercase tracking-wider text-textmid transition hover:border-gold hover:text-gold disabled:opacity-30"
        >
          Back
        </button>
        {step < STEPS.length - 1 ? (
          <button
            type="button"
            onClick={() => {
              setResult(null);
              setStep((s) => s + 1);
            }}
            className="rounded bg-gold px-6 py-2 text-sm font-bold text-black transition hover:bg-gold2"
          >
            Continue
          </button>
        ) : (
          <button
            type="button"
            disabled={saving}
            onClick={activate}
            className="rounded bg-gold px-6 py-2 text-sm font-bold text-black transition hover:bg-gold2 disabled:opacity-50"
          >
            {saving ? "Activating…" : "Activate system"}
          </button>
        )}
      </div>
    </div>
  );
}

// ── small building blocks ────────────────────────────────────────────────
function Stepper({ step }: { step: number }) {
  return (
    <div className="flex gap-2">
      {STEPS.map((s, i) => (
        <div key={s} className="flex-1">
          <div className={`h-1 rounded ${i <= step ? "bg-gold" : "bg-border"}`} />
          <div className={`mt-1 font-mono text-[9px] uppercase tracking-wider ${i === step ? "text-gold" : "text-textdim"}`}>
            {i + 1}. {s}
          </div>
        </div>
      ))}
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-textdim">
      {children}
    </label>
  );
}

function Field({
  label, value, onChange, type = "text", placeholder,
}: {
  label: string; value: string; onChange: (v: string) => void; type?: string; placeholder?: string;
}) {
  return (
    <div>
      <Label>{label}</Label>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
        className="w-full rounded border border-border bg-bg3 px-3 py-2 text-sm outline-none focus:border-gold"
      />
    </div>
  );
}

function NumberField({
  label, value, onChange, step = 1,
}: {
  label: string; value: number; onChange: (v: number) => void; step?: number;
}) {
  return (
    <div>
      <Label>{label}</Label>
      <input
        type="number"
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full rounded border border-border bg-bg3 px-3 py-2 text-sm outline-none focus:border-gold"
      />
    </div>
  );
}

function SelectField({
  label, value, onChange, options,
}: {
  label: string; value: string; onChange: (v: string) => void; options: [string, string][];
}) {
  return (
    <div>
      <Label>{label}</Label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded border border-border bg-bg3 px-3 py-2 text-sm outline-none focus:border-gold"
      >
        {options.map(([v, l]) => (
          <option key={v} value={v}>{l}</option>
        ))}
      </select>
    </div>
  );
}

function TestRow({
  testing, result, onTest, label,
}: {
  testing: boolean; result: FieldValidation | null; onTest: () => void; label: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={onTest}
        disabled={testing}
        className="rounded border border-border px-4 py-2 font-mono text-[11px] uppercase tracking-wider text-textmid transition hover:border-gold hover:text-gold disabled:opacity-50"
      >
        {testing ? "Testing…" : label}
      </button>
      {result && (
        <span className={`text-xs ${result.ok ? "text-up" : "text-down"}`}>
          {result.ok ? "✓ " : "✕ "}
          {result.detail}
        </span>
      )}
    </div>
  );
}

function Review({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-border py-2 text-sm">
      <span className="text-textdim">{label}</span>
      <span className="text-right font-mono text-textmid">{value}</span>
    </div>
  );
}
