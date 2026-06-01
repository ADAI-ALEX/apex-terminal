"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  getOnboardingStatus,
  saveSettings,
  type OnboardingStatus,
  type SettingsUpdate,
} from "@/lib/onboarding";

const MODELS: [string, string][] = [
  ["claude-opus-4-8", "Claude Opus 4.8 (most capable)"],
  ["claude-sonnet-4-6", "Claude Sonnet 4.6 (balanced — default)"],
  ["claude-haiku-4-5-20251001", "Claude Haiku 4.5 (fastest / cheapest)"],
];
const PROFILES: [string, string][] = [
  ["prop_ftmo", "Prop Firm — Conservative"],
  ["ig_standard", "IG Standard"],
];
const ALL_MARKETS = ["US500", "NAS100", "EURUSD", "GBPUSD", "FTSE100", "DAX40"];

export default function SettingsPage() {
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [claudeKey, setClaudeKey] = useState("");
  const [model, setModel] = useState("claude-sonnet-4-6");
  const [profile, setProfile] = useState("prop_ftmo");
  const [markets, setMarkets] = useState<string[]>([]);
  const [tradingEnabled, setTradingEnabled] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void (async () => {
      const s = await getOnboardingStatus();
      if (!s) return;
      setStatus(s);
      setModel(s.claude_model || "claude-sonnet-4-6");
      setProfile(s.risk_profile || "prop_ftmo");
      setMarkets(s.active_markets ?? []);
      setTradingEnabled(!!s.trading_enabled);
    })();
  }, []);

  function toggleMarket(m: string) {
    setMarkets((cur) => (cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m]));
    setSaved(false);
  }

  async function save() {
    setSaving(true);
    setSaved(false);
    const update: SettingsUpdate = {
      anthropic: { model, ...(claudeKey ? { api_key: claudeKey } : {}) },
      risk: { profile, active_markets: markets, trading_enabled: tradingEnabled },
    };
    const res = await saveSettings(update);
    setSaving(false);
    setSaved(res.ok);
    if (res.ok) setClaudeKey("");
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-6 sm:px-8">
      <header className="mb-6 flex items-center justify-between border-b border-border pb-4">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.3em] text-gold">
            ADAI Systems · Settings
          </div>
          <h1 className="text-2xl font-bold">Configuration</h1>
        </div>
        <Link
          href="/"
          className="rounded border border-border px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-textmid transition hover:border-gold hover:text-gold"
        >
          ← Dashboard
        </Link>
      </header>

      <div className="space-y-6">
        {/* Claude AI */}
        <section className="rounded-md border border-border bg-bg2 p-5">
          <h2 className="mb-3 text-sm font-bold text-gold">Claude AI</h2>
          <Label>Anthropic API key {status?.claude_enabled && <span className="text-up">(set — leave blank to keep)</span>}</Label>
          <input
            type="password"
            value={claudeKey}
            placeholder={status?.claude_enabled ? "•••• stored" : "sk-ant-…"}
            onChange={(e) => { setClaudeKey(e.target.value); setSaved(false); }}
            autoComplete="off"
            className="mb-4 w-full rounded border border-border bg-bg3 px-3 py-2 text-sm outline-none focus:border-gold"
          />
          <Label>Model</Label>
          <Select value={model} onChange={(v) => { setModel(v); setSaved(false); }} options={MODELS} />
        </section>

        {/* Trading */}
        <section className="rounded-md border border-border bg-bg2 p-5">
          <h2 className="mb-3 text-sm font-bold text-gold">Trading</h2>
          <Label>Risk profile</Label>
          <Select value={profile} onChange={(v) => { setProfile(v); setSaved(false); }} options={PROFILES} />
          <div className="mt-4">
            <Label>Instruments</Label>
            <div className="mt-1 flex flex-wrap gap-2">
              {ALL_MARKETS.map((m) => {
                const on = markets.includes(m);
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
          <label className="mt-4 flex items-center gap-3 rounded border border-border bg-bg3 p-3">
            <input
              type="checkbox"
              checked={tradingEnabled}
              onChange={(e) => { setTradingEnabled(e.target.checked); setSaved(false); }}
              className="h-4 w-4 accent-gold"
            />
            <span className="text-sm">
              Live order placement
              <span className="block text-xs text-textdim">Off = monitor only (no orders placed).</span>
            </span>
          </label>
        </section>

        <div className="flex items-center gap-4">
          <button
            type="button"
            disabled={saving}
            onClick={save}
            className="rounded bg-gold px-6 py-2 text-sm font-bold text-black transition hover:bg-gold2 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
          {saved && <span className="text-sm text-up">✓ Saved — your engine applies it within ~20s.</span>}
        </div>
        <p className="text-xs text-textdim">
          IG account credentials are set during onboarding. To change them, use the
          onboarding wizard (reset from the algo) — they aren't editable here for safety.
        </p>
      </div>
    </main>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-textdim">
      {children}
    </label>
  );
}

function Select({
  value, onChange, options,
}: {
  value: string; onChange: (v: string) => void; options: [string, string][];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded border border-border bg-bg3 px-3 py-2 text-sm outline-none focus:border-gold"
    >
      {options.map(([v, l]) => (
        <option key={v} value={v}>{l}</option>
      ))}
    </select>
  );
}
