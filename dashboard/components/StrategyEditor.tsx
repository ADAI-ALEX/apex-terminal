"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

// Lightweight, dependency-free code editor for custom backtest strategies.
// A transparent <textarea> sits over a syntax-highlighted <pre> mirror (the
// classic overlay technique) so we get highlighting + line numbers with zero
// extra libraries — guaranteed to build and run offline on Vercel.

export type Strategy = {
  name: string; label: string; description: string;
  kind: "builtin" | "default" | "custom"; editable: boolean; code: string;
};

type SaveState = { status: "idle" | "saving" | "saved" | "error"; msg?: string };

const AUTOSAVE_MS = 2000;

const PY_KEYWORDS = new Set([
  "if", "elif", "else", "and", "or", "not", "in", "is", "for", "while", "return",
  "True", "False", "None", "def", "break", "continue", "pass", "import", "as", "with",
]);
// Cheat-sheet identifiers (variables + functions injected into the sandbox).
const API_NAMES = new Set([
  "open", "high", "low", "close", "volume", "price", "fear_and_greed", "fear_greed",
  "vix", "sentiment", "sma", "ema", "rsi", "macd", "atr", "adx", "bollinger",
  "highest", "lowest", "crossover", "crossunder", "signal", "isnan", "nan", "i", "n",
]);

const CHEATSHEET: { group: string; items: [string, string][] }[] = [
  {
    group: "Price (current bar)",
    items: [
      ["open high low close", "OHLC of the current bar"],
      ["volume", "bar volume"],
      ["price", "alias for close"],
    ],
  },
  {
    group: "Niche / exogenous",
    items: [
      ["fear_and_greed", "Fear & Greed index, 0–100"],
      ["vix", "CBOE Volatility Index"],
      ["sentiment", "short-horizon sentiment, −100…+100"],
    ],
  },
  {
    group: "Indicators",
    items: [
      ["sma(p)", "simple moving average"],
      ["ema(p)", "exponential moving average"],
      ["rsi(p)", "relative strength index"],
      ["macd()", "→ (line, signal, hist)"],
      ["atr(p)", "average true range"],
      ["adx(p)", "trend strength"],
      ["bollinger(p, s)", "→ (upper, mid, lower)"],
      ["highest(p) lowest(p)", "rolling high / low"],
    ],
  },
  {
    group: "Signals & logic",
    items: [
      ['signal = "BUY"', "open a long (ATR-sized)"],
      ['signal = "SELL"', "open a short"],
      ['signal = "FLAT"', "close any open position"],
      ['signal = "HOLD"', "do nothing; let SL/TP manage"],
      ["crossover(a, b)", "a crosses above b"],
      ["crossunder(a, b)", "a crosses below b"],
    ],
  },
];

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Token-based highlighter: comments, strings, numbers, then keyword/api/plain words.
function highlight(code: string): string {
  const re = /(#[^\n]*)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(\d+\.?\d*)|([A-Za-z_]\w*)/g;
  let out = "";
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(code)) !== null) {
    out += escapeHtml(code.slice(last, m.index));
    const [tok] = m;
    if (m[1]) out += `<span class="tk-com">${escapeHtml(tok)}</span>`;
    else if (m[2]) out += `<span class="tk-str">${escapeHtml(tok)}</span>`;
    else if (m[3]) out += `<span class="tk-num">${escapeHtml(tok)}</span>`;
    else if (PY_KEYWORDS.has(tok)) out += `<span class="tk-kw">${escapeHtml(tok)}</span>`;
    else if (API_NAMES.has(tok)) out += `<span class="tk-api">${escapeHtml(tok)}</span>`;
    else out += escapeHtml(tok);
    last = m.index + tok.length;
  }
  out += escapeHtml(code.slice(last));
  return out + "\n"; // trailing newline keeps the last line visible under the caret
}

export function StrategyEditor({
  initial, onClose, onSaved, onDeleted,
}: {
  initial: Strategy;
  onClose: () => void;
  onSaved: (s: Strategy) => void;
  onDeleted: (name: string) => void;
}) {
  const isNew = initial.name === ""; // new drafts arrive with an empty name
  const [name, setName] = useState(initial.name);
  const [code, setCode] = useState(initial.code);
  const [save, setSave] = useState<SaveState>({ status: "idle" });
  const taRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const gutterRef = useRef<HTMLDivElement>(null);
  const savedRef = useRef<{ name: string; code: string }>({ name: initial.name, code: initial.code });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const nameValid = /^[A-Za-z0-9][A-Za-z0-9_-]{0,48}$/.test(name);
  const lineCount = useMemo(() => code.split("\n").length, [code]);

  const doSave = useCallback(async (n: string, c: string) => {
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,48}$/.test(n)) {
      setSave({ status: "error", msg: "Name must be letters/numbers/-/_ (no spaces)." });
      return;
    }
    setSave({ status: "saving" });
    try {
      const res = await fetch("/api/strategies", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "save", name: n, code: c }),
      });
      const data = (await res.json()) as { ok?: boolean; error?: string; pending?: boolean };
      if (data.ok === false) { setSave({ status: "error", msg: data.error ?? "Save failed." }); return; }
      savedRef.current = { name: n, code: c };
      setSave({ status: "saved", msg: data.pending ? "Queued (engine offline) — saves when it reconnects." : undefined });
      onSaved({ ...initial, name: n, code: c, kind: "custom", editable: true, label: n });
    } catch {
      setSave({ status: "error", msg: "Network error while saving." });
    }
  }, [initial, onSaved]);

  // Debounced auto-save: 2s after the user stops typing (name or code change).
  useEffect(() => {
    if (name === savedRef.current.name && code === savedRef.current.code) return;
    if (!nameValid) { setSave({ status: "error", msg: "Enter a valid name to enable auto-save." }); return; }
    setSave({ status: "idle" });
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => doSave(name, code), AUTOSAVE_MS);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [name, code, nameValid, doSave]);

  const syncScroll = useCallback(() => {
    if (preRef.current && taRef.current) {
      preRef.current.scrollTop = taRef.current.scrollTop;
      preRef.current.scrollLeft = taRef.current.scrollLeft;
    }
    if (gutterRef.current && taRef.current) gutterRef.current.scrollTop = taRef.current.scrollTop;
  }, []);

  const onKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const ta = e.currentTarget;
      const s = ta.selectionStart, end = ta.selectionEnd;
      const next = code.slice(0, s) + "    " + code.slice(end);
      setCode(next);
      requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = s + 4; });
    }
  }, [code]);

  async function handleDelete() {
    if (!confirm(`Delete custom strategy "${name}"? This cannot be undone.`)) return;
    setSave({ status: "saving" });
    try {
      await fetch("/api/strategies", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "delete", name }),
      });
      onDeleted(name);
    } catch {
      setSave({ status: "error", msg: "Delete failed." });
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-3 sm:p-6" onClick={onClose}>
      <div
        className="flex h-full max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-lg border border-border bg-bg2 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
          <span className="font-mono text-[10px] uppercase tracking-wider text-gold">// Custom Strategy Editor</span>
          <div className="flex items-center gap-2">
            <label className="font-mono text-[9px] uppercase tracking-wider text-textdim">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value.replace(/\s+/g, "_"))}
              readOnly={!isNew}
              placeholder="my_strategy"
              className={`w-48 rounded border px-2 py-1 font-mono text-sm outline-none ${nameValid || !name ? "border-border" : "border-down"} bg-bg3 ${!isNew ? "opacity-70" : "focus:border-gold"}`}
            />
            {!isNew && <span className="font-mono text-[9px] text-textdim">(name locked)</span>}
          </div>
          <SaveBadge save={save} />
          <div className="ml-auto flex items-center gap-2">
            {initial.editable && (
              <button onClick={handleDelete} className="rounded border border-down/40 bg-down/10 px-3 py-1.5 text-xs font-bold text-down hover:bg-down/20">Delete</button>
            )}
            <button onClick={() => doSave(name, code)} disabled={!nameValid} className="rounded bg-gold px-4 py-1.5 text-xs font-bold text-black hover:bg-gold2 disabled:opacity-50">Save now</button>
            <button onClick={onClose} className="rounded border border-border bg-bg3 px-3 py-1.5 text-xs font-bold text-textmid hover:text-gold">Close</button>
          </div>
        </div>

        {/* Body: editor + cheat-sheet sidebar */}
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          {/* Editor */}
          <div className="relative flex min-h-0 flex-1 overflow-hidden bg-[#0a0a0a] font-mono text-[13px] leading-[1.5]">
            <div ref={gutterRef} className="select-none overflow-hidden border-r border-border/60 bg-bg2/40 py-3 pl-3 pr-2 text-right text-textdim/60" aria-hidden>
              {Array.from({ length: lineCount }, (_, i) => <div key={i}>{i + 1}</div>)}
            </div>
            <div className="relative min-h-0 flex-1">
              <pre
                ref={preRef}
                aria-hidden
                className="pointer-events-none absolute inset-0 m-0 overflow-auto whitespace-pre p-3 text-textmid"
                dangerouslySetInnerHTML={{ __html: highlight(code) }}
              />
              <textarea
                ref={taRef}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                onScroll={syncScroll}
                onKeyDown={onKeyDown}
                spellCheck={false}
                autoCapitalize="off"
                autoCorrect="off"
                className="absolute inset-0 m-0 resize-none overflow-auto whitespace-pre bg-transparent p-3 text-transparent caret-gold outline-none"
              />
            </div>
          </div>

          {/* Cheat sheet */}
          <aside className="min-h-0 w-full shrink-0 overflow-auto border-t border-border bg-bg2 p-3 lg:w-72 lg:border-l lg:border-t-0">
            <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-gold">// Cheat Sheet</div>
            <p className="mb-3 text-[11px] leading-snug text-textdim">
              Runs once per bar against 20 years of local daily data. Set <code className="text-tk-api">signal</code>. Click any token to insert it.
            </p>
            {CHEATSHEET.map((sec) => (
              <div key={sec.group} className="mb-3">
                <div className="mb-1 font-mono text-[9px] uppercase tracking-wider text-textmid">{sec.group}</div>
                <div className="space-y-1">
                  {sec.items.map(([token, desc]) => (
                    <button
                      key={token}
                      onClick={() => insertAtCursor(taRef, token.split(" ")[0], setCode)}
                      className="block w-full rounded border border-border/60 bg-bg3 px-2 py-1 text-left transition hover:border-gold/50"
                      title={`Insert ${token}`}
                    >
                      <div className="font-mono text-[11px] text-gold">{token}</div>
                      <div className="text-[10px] text-textdim">{desc}</div>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </aside>
        </div>
      </div>

      {/* token colours for the highlighter (scoped, theme-aware) */}
      <style jsx global>{`
        .tk-com { color: #6b7280; font-style: italic; }
        .tk-str { color: #86c06c; }
        .tk-num { color: #d39e5c; }
        .tk-kw  { color: #c084fc; }
        .tk-api { color: #c9a84c; }
        .text-tk-api { color: #c9a84c; }
      `}</style>
    </div>
  );
}

function insertAtCursor(
  taRef: React.RefObject<HTMLTextAreaElement>,
  text: string,
  setCode: (updater: (c: string) => string) => void,
) {
  const ta = taRef.current;
  if (!ta) { setCode((c) => c + text); return; }
  const s = ta.selectionStart, e = ta.selectionEnd;
  setCode((c) => c.slice(0, s) + text + c.slice(e));
  requestAnimationFrame(() => { ta.focus(); ta.selectionStart = ta.selectionEnd = s + text.length; });
}

function SaveBadge({ save }: { save: SaveState }) {
  const map = {
    idle: ["•", "text-textdim", "Auto-save on"],
    saving: ["⟳", "text-info animate-pulse", "Saving…"],
    saved: ["✓", "text-up", save.msg ?? "Saved"],
    error: ["!", "text-down", save.msg ?? "Error"],
  } as const;
  const [icon, cls, label] = map[save.status];
  return (
    <span className={`flex items-center gap-1 font-mono text-[11px] ${cls}`} title={label}>
      <span>{icon}</span><span className="max-w-[22rem] truncate">{label}</span>
    </span>
  );
}
