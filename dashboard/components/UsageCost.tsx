"use client";

import type { AlgoState } from "@/lib/types";

/**
 * AI usage & cost tab. Shows whether the Claude "brain" is on, how many calls have
 * been made this session, token counts, and an estimated USD cost.
 */
export function UsageCost({ state }: { state: AlgoState }) {
  const u = state.claude_usage ?? { calls: 0, input_tokens: 0, output_tokens: 0, est_cost_usd: 0 };
  const on = state.ai_enabled !== false;

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      <div className="flex items-center justify-between rounded border border-border bg-bg3 px-3 py-2">
        <span className="font-mono text-[11px] uppercase tracking-wider text-textdim">AI brain (Claude)</span>
        <span className={`rounded px-2 py-0.5 font-mono text-[11px] font-bold ${on ? "bg-up/10 text-up" : "bg-textdim/10 text-textdim"}`}>
          {on ? "ON" : "OFF"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Stat label="Calls (session)" value={u.calls.toLocaleString()} />
        <Stat label="Est. cost" value={`$${u.est_cost_usd.toFixed(4)}`} accent />
        <Stat label="Input tokens" value={u.input_tokens.toLocaleString()} />
        <Stat label="Output tokens" value={u.output_tokens.toLocaleString()} />
      </div>

      <div className="rounded border border-border bg-bg3 px-3 py-2 font-mono text-[10px] leading-relaxed text-textdim">
        Tier-2 (signal) calls run ~every 5m per qualifying signal; Tier-3 (portfolio)
        ~every 30m; EOD once daily. Turn the brain off in Settings to run pure-Python
        with zero AI cost. Cost is an estimate from list prices, reset on engine restart.
      </div>

      {!on && (
        <div className="rounded border border-gold/30 bg-gold/5 px-3 py-2 text-xs text-gold">
          The AI brain is off — Python executes and protects every order on its own; no
          Claude calls are made.
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded border border-border bg-bg3 px-3 py-2">
      <div className="font-mono text-[9px] uppercase tracking-wider text-textdim">{label}</div>
      <div className={`mt-0.5 text-lg font-bold ${accent ? "text-gold" : "text-textmid"}`}>{value}</div>
    </div>
  );
}
