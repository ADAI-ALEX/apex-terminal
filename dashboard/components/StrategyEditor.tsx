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

/** Display name -> filename slug (spaces become underscores). */
function slugify(label: string): string {
  return label.trim().replace(/\s+/g, "_").replace(/[^A-Za-z0-9_-]/g, "").slice(0, 49);
}
function slugValid(slug: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9_-]{0,48}$/.test(slug);
}

const PY_KEYWORDS = new Set([
  "if", "elif", "else", "and", "or", "not", "in", "is", "for", "while", "return",
  "True", "False", "None", "def", "break", "continue", "pass", "import", "as", "with",
]);
const API_NAMES = new Set([
  "open", "high", "low", "close", "volume", "price", "fear_and_greed", "fear_greed",
  "vix", "sentiment", "sma", "ema", "rsi", "macd", "atr", "adx", "bollinger",
  "highest", "lowest", "donchian", "roc", "stdev", "vwap", "crossover", "crossunder",
  "volume_profile", "cvd", "markov",
  "signal", "risk", "stop_mult", "target_rr", "scale_at", "scale_frac", "scale_be",
  "isnan", "nan", "i", "n",
  "hour", "minute", "dow",
  "position", "bars_held", "equity", "risk_pct", "leverage",
  "day_pnl_pct", "consec_losses", "consec_wins", "trades_today",
  "dd_from_peak_pct", "total_pnl_pct",
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
    group: "Exogenous",
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
      ["donchian(p)", "→ (upper, lower) highest/lowest close"],
      ["roc(n)", "close-to-close % return over n bars"],
      ["stdev(p)", "rolling volatility (std of closes)"],
      ["vwap(p)", "rolling volume-weighted average price"],
      ["highest(p) lowest(p)", "rolling high / low"],
    ],
  },
  {
    group: "Auction & order flow",
    items: [
      ["volume_profile(p, bins)", "→ (poc, vah, val, lvn, width)"],
      ["·  poc", "Point of Control — fair-value magnet"],
      ["·  vah / val", "Value-Area High/Low (≈70% volume band)"],
      ["·  lvn / width", "low-volume node / value-area width"],
      ["cvd(p)", "cumulative volume delta (order-flow pressure)"],
      ["markov(lookback)", "regime engine → (state, edge, p_bull, …)"],
    ],
  },
  {
    group: "Session clock (UTC)",
    items: [
      ["hour, minute", "bar time — e.g. 13≤hour<20 = New York"],
      ["dow", "day of week (0=Mon … 4=Fri)"],
    ],
  },
  {
    group: "Strategy state",
    items: [
      ["position", "current position: 1 long, -1 short, 0 flat"],
      ["bars_held", "bars since the position opened"],
      ["equity", "current account equity (£)"],
      ["risk_pct", "configured risk %/trade"],
      ["leverage", "instrument max leverage"],
    ],
  },
  {
    group: "Prop-firm risk (FTMO)",
    items: [
      ["day_pnl_pct", "running P&L since the day opened (%)"],
      ["dd_from_peak_pct", "drawdown from the equity peak (%)"],
      ["total_pnl_pct", "P&L since inception (%)"],
      ["consec_losses / wins", "current closed-trade streak"],
      ["trades_today", "trades opened so far today"],
    ],
  },
  {
    group: "Signals & logic",
    items: [
      ['signal = "BUY"', "open a long (ATR-sized)"],
      ['signal = "SELL"', "open a short"],
      ['signal = "FLAT"', "close any open position"],
      ['signal = "HOLD"', "do nothing; let SL/TP manage"],
      ["risk = 0.5", "override this trade's risk % (optional)"],
      ["stop_mult / target_rr", "override stop (×ATR) / reward:risk"],
      ["scale_at = poc", "scale out part of the position at a price level"],
      ["scale_frac / scale_be", "fraction to scale (0–0.95) / move stop to break-even"],
      ["crossover(a, b)", "a crosses above b"],
      ["crossunder(a, b)", "a crosses below b"],
    ],
  },
];

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

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
  return out + "\n";
}

export function StrategyEditor({
  initial, existingNames = [], onClose, onSaved, onDelete,
}: {
  initial: Strategy;
  existingNames?: string[]; // slugs already in use — used to block duplicate names
  onClose: () => void;
  onSaved: (s: Strategy) => void;
  onDelete: (slug: string) => void; // parent removes it from the list + closes (optimistic)
}) {
  const isNew = initial.name === ""; // new drafts arrive with an empty slug
  const [label, setLabel] = useState(initial.label || "");
  const [code, setCode] = useState(initial.code);
  // First save must be manual; auto-save only kicks in afterwards (existing strategies are already saved).
  const [savedOnce, setSavedOnce] = useState(!isNew);
  const [save, setSave] = useState<SaveState>(isNew ? { status: "idle" } : { status: "saved", msg: "Saved" });
  const [confirmDelete, setConfirmDelete] = useState(false);

  const taRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const gutterRef = useRef<HTMLDivElement>(null);
  const savedRef = useRef<{ label: string; code: string }>({ label: initial.label, code: initial.code });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Undo/redo history (a controlled textarea breaks the browser's native stack).
  const undoRef = useRef<string[]>([]);
  const redoRef = useRef<string[]>([]);
  const lastCommit = useRef(0);
  const [findOpen, setFindOpen] = useState(false);
  const [findText, setFindText] = useState("");
  const findRef = useRef<HTMLInputElement>(null);
  // Only close on a click that BOTH starts and ends on the backdrop — so dragging
  // (e.g. selecting text) out onto the backdrop never closes the editor.
  const downOnBackdrop = useRef(false);

  const slug = isNew ? slugify(label) : initial.name;
  const valid = label.trim().length > 0 && slugValid(slug);
  const lineCount = useMemo(() => code.split("\n").length, [code]);

  const doSave = useCallback(async (l: string, c: string) => {
    const sg = isNew ? slugify(l) : initial.name;
    if (!l.trim() || !slugValid(sg)) {
      setSave({ status: "error", msg: "Enter a name (letters/numbers/spaces)." });
      return;
    }
    if (isNew && existingNames.includes(sg)) {
      setSave({ status: "error", msg: `Name "${l.trim()}" is already taken — choose a unique name.` });
      return;
    }
    setSave({ status: "saving" });
    try {
      const res = await fetch("/api/strategies", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "save", name: sg, label: l.trim(), code: c }),
      });
      const data = (await res.json()) as { ok?: boolean; error?: string; pending?: boolean };
      if (data.ok === false) { setSave({ status: "error", msg: data.error ?? "Save failed." }); return; }
      savedRef.current = { label: l, code: c };
      setSavedOnce(true);
      setSave({ status: "saved", msg: data.pending ? "Queued — saves when the engine reconnects." : "Saved" });
      onSaved({ name: sg, label: l.trim(), description: initial.description, kind: "custom", editable: true, code: c });
    } catch {
      setSave({ status: "error", msg: "Network error while saving." });
    }
  }, [initial.name, initial.description, isNew, onSaved, existingNames]);

  // Debounced auto-save — only AFTER the first manual save.
  useEffect(() => {
    if (!savedOnce) return;
    if (label === savedRef.current.label && code === savedRef.current.code) return;
    if (!valid) { setSave({ status: "error", msg: "Enter a valid name to keep auto-saving." }); return; }
    setSave({ status: "idle" });
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => doSave(label, code), AUTOSAVE_MS);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [label, code, valid, savedOnce, doSave]);

  const syncScroll = useCallback(() => {
    if (preRef.current && taRef.current) {
      preRef.current.scrollTop = taRef.current.scrollTop;
      preRef.current.scrollLeft = taRef.current.scrollLeft;
    }
    if (gutterRef.current && taRef.current) gutterRef.current.scrollTop = taRef.current.scrollTop;
  }, []);

  // Record the pre-change value, coalescing fast typing into ~400ms chunks.
  const pushHistory = useCallback((prev: string, coalesce: boolean) => {
    const now = Date.now();
    if (!coalesce || undoRef.current.length === 0 || now - lastCommit.current > 400) {
      undoRef.current.push(prev);
      if (undoRef.current.length > 300) undoRef.current.shift();
      redoRef.current = [];
      lastCommit.current = now;
    }
  }, []);
  const changeCode = useCallback((next: string, coalesce = true) => {
    pushHistory(code, coalesce);
    setCode(next);
  }, [pushHistory, code]);
  const undo = useCallback(() => {
    if (!undoRef.current.length) return;
    redoRef.current.push(code);
    setCode(undoRef.current.pop() as string);
    lastCommit.current = Date.now();
  }, [code]);
  const redo = useCallback(() => {
    if (!redoRef.current.length) return;
    undoRef.current.push(code);
    setCode(redoRef.current.pop() as string);
    lastCommit.current = Date.now();
  }, [code]);
  const insertToken = useCallback((token: string) => {
    const ta = taRef.current;
    if (!ta) { changeCode(code + token, false); return; }
    const s = ta.selectionStart, e = ta.selectionEnd;
    changeCode(code.slice(0, s) + token + code.slice(e), false);
    requestAnimationFrame(() => { ta.focus(); ta.selectionStart = ta.selectionEnd = s + token.length; });
  }, [code, changeCode]);
  const findNext = useCallback(() => {
    const ta = taRef.current;
    if (!ta || !findText) return;
    const from = ta.selectionEnd ?? 0;
    let i = code.indexOf(findText, from);
    if (i < 0) i = code.indexOf(findText, 0); // wrap to top
    if (i < 0) return;
    ta.focus();
    ta.setSelectionRange(i, i + findText.length);
    const line = code.slice(0, i).split("\n").length;
    ta.scrollTop = Math.max(0, (line - 3) * 19.5); // ~13px * 1.5 line-height
    requestAnimationFrame(syncScroll);
  }, [code, findText, syncScroll]);

  const onKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const mod = e.ctrlKey || e.metaKey;
    if (e.key === "Tab") {
      e.preventDefault();
      const ta = e.currentTarget;
      const s = ta.selectionStart, end = ta.selectionEnd;
      changeCode(code.slice(0, s) + "    " + code.slice(end), false);
      requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = s + 4; });
      return;
    }
    const k = e.key.toLowerCase();
    if (mod && k === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if (mod && k === "y") { e.preventDefault(); redo(); return; }
    if (mod && k === "s") { e.preventDefault(); doSave(label, code); return; }
    if (mod && k === "f") { e.preventDefault(); setFindOpen(true); requestAnimationFrame(() => findRef.current?.select()); return; }
    if (e.key === "Escape" && findOpen) { setFindOpen(false); }
  }, [code, changeCode, undo, redo, doSave, label, findOpen]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-3 sm:p-6"
      onMouseDown={(e) => { downOnBackdrop.current = e.target === e.currentTarget; }}
      onClick={(e) => { if (downOnBackdrop.current && e.target === e.currentTarget) onClose(); downOnBackdrop.current = false; }}
    >
      <div
        className="flex h-full max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-lg border border-border bg-bg2 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
          <span className="font-mono text-[10px] uppercase tracking-wider text-gold">// {isNew ? "New" : "Edit"} Strategy</span>
          <div className="flex items-center gap-2">
            <label className="font-mono text-[9px] uppercase tracking-wider text-textdim">Name</label>
            <div>
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="My Strategy"
                className={`w-56 rounded border px-2 py-1 font-mono text-sm outline-none bg-bg3 ${valid || !label ? "border-border focus:border-gold" : "border-down"}`}
              />
              {label && (
                <div className="mt-0.5 font-mono text-[9px] text-textdim">saved as <span className="text-textmid">{slug || "—"}.py</span></div>
              )}
            </div>
          </div>
          <SaveBadge save={save} savedOnce={savedOnce} />
          <div className="ml-auto flex items-center gap-2">
            {savedOnce && (
              <button onClick={() => setConfirmDelete(true)} className="rounded border border-down/40 bg-down/10 px-3 py-1.5 text-xs font-bold text-down hover:bg-down/20">Delete</button>
            )}
            <button onClick={() => doSave(label, code)} disabled={save.status === "saving"} className="btn-gold rounded px-4 py-1.5 text-xs font-bold">
              {savedOnce ? "Save now" : "Save"}
            </button>
            <button onClick={onClose} className="rounded border border-border bg-bg3 px-3 py-1.5 text-xs font-bold text-textmid hover:text-gold">Close</button>
          </div>
        </div>

        {/* Body: editor + cheat-sheet sidebar */}
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <div className="relative flex min-h-0 flex-1 overflow-hidden bg-[#0a0a0a] font-mono text-[13px] leading-[1.5]">
            {/* The editor is always dark, so gutter + default text use fixed
                light-on-dark colours (theme vars would be invisible in light mode). */}
            <div ref={gutterRef} className="select-none overflow-hidden border-r border-[#2a2a2a] bg-black/30 py-3 pl-3 pr-2 text-right text-[#8a8a93]" aria-hidden>
              {Array.from({ length: lineCount }, (_, i) => <div key={i}>{i + 1}</div>)}
            </div>
            <div className="relative min-h-0 flex-1">
              <pre
                ref={preRef}
                aria-hidden
                className="pointer-events-none absolute inset-0 m-0 overflow-auto whitespace-pre p-3 text-[#d4d4d4]"
                dangerouslySetInnerHTML={{ __html: highlight(code) }}
              />
              <textarea
                ref={taRef}
                value={code}
                onChange={(e) => changeCode(e.target.value)}
                onScroll={syncScroll}
                onKeyDown={onKeyDown}
                spellCheck={false}
                autoCapitalize="off"
                autoCorrect="off"
                className="absolute inset-0 m-0 resize-none overflow-auto whitespace-pre bg-transparent p-3 text-transparent caret-gold outline-none"
              />
              {findOpen && (
                <div className="absolute right-2 top-2 z-20 flex items-center gap-1 rounded border border-border bg-bg2 px-2 py-1 shadow-lg">
                  <span className="font-mono text-[10px] text-textdim">find</span>
                  <input
                    ref={findRef}
                    value={findText}
                    onChange={(e) => setFindText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") { e.preventDefault(); findNext(); }
                      else if (e.key === "Escape") { setFindOpen(false); taRef.current?.focus(); }
                    }}
                    placeholder="text…"
                    className="w-32 bg-transparent font-mono text-[12px] text-textmid outline-none"
                  />
                  <button onClick={findNext} title="Next (Enter)" className="px-1 font-mono text-[12px] text-textdim hover:text-gold">↵</button>
                  <button onClick={() => { setFindOpen(false); taRef.current?.focus(); }} title="Close (Esc)" className="px-1 font-mono text-[12px] text-textdim hover:text-gold">✕</button>
                </div>
              )}
            </div>
          </div>

          <aside className="min-h-0 w-full shrink-0 overflow-auto border-t border-border bg-bg2 p-3 lg:w-72 lg:border-l lg:border-t-0">
            <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-gold">// Cheat Sheet</div>
            <p className="mb-2 text-[11px] leading-snug text-textdim">
              Runs once per bar against local daily data. Set <code className="text-tk-api">signal</code>. Click any token to insert it.
            </p>
            <div className="mb-3 font-mono text-[9px] leading-relaxed text-textdim">
              <span className="text-textmid">Keys:</span> Ctrl+Z undo · Ctrl+Y redo · Ctrl+F find · Ctrl+S save · Tab indent
            </div>
            {CHEATSHEET.map((sec) => (
              <div key={sec.group} className="mb-3">
                <div className="mb-1 font-mono text-[9px] uppercase tracking-wider text-textmid">{sec.group}</div>
                <div className="space-y-1">
                  {sec.items.map(([token, desc]) => (
                    <button
                      key={token}
                      onClick={() => insertToken(token.split(" ")[0])}
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

      {/* In-app delete confirmation — same style as the Sign-out modal */}
      {confirmDelete && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4" onClick={(e) => { e.stopPropagation(); setConfirmDelete(false); }}>
          <div className="w-full max-w-sm rounded-md border border-border bg-bg2 p-6" onClick={(e) => e.stopPropagation()}>
            <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.3em] text-gold">Apex Algo</div>
            <h2 className="mb-2 text-lg font-bold">Delete strategy?</h2>
            <p className="mb-6 text-sm text-textmid">
              This permanently removes <span className="font-bold text-gold">{label || slug}</span>
              <span className="font-mono text-textdim"> ({slug}.py)</span> and cannot be undone.
            </p>
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setConfirmDelete(false)}
                className="rounded border border-border px-4 py-2 font-mono text-[11px] uppercase tracking-wider text-textmid transition hover:border-gold hover:text-gold"
              >Cancel</button>
              <button
                type="button"
                onClick={() => { setConfirmDelete(false); onDelete(slug); }}
                className="rounded bg-down px-4 py-2 text-sm font-bold text-white transition hover:opacity-90"
              >Delete</button>
            </div>
          </div>
        </div>
      )}

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

function SaveBadge({ save, savedOnce }: { save: SaveState; savedOnce: boolean }) {
  if (!savedOnce && save.status === "idle") {
    return <span className="font-mono text-[11px] text-textdim" title="Save once to enable auto-save">Save to enable auto-save</span>;
  }
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
