"use client";

import { useEffect, useState } from "react";
import { applyTheme, getMode, type ThemeMode } from "@/lib/theme";

const NEXT: Record<ThemeMode, ThemeMode> = { dark: "light", light: "auto", auto: "dark" };
const ICON: Record<ThemeMode, string> = { dark: "🌙", light: "☀", auto: "◐" };

/** Small header control that cycles Dark → Light → Auto. */
export function ThemeToggle() {
  const [mode, setMode] = useState<ThemeMode>("dark");

  useEffect(() => {
    const m = getMode();
    setMode(m);
    applyTheme(m);
    // Re-evaluate "auto" every few minutes so it flips at dawn/dusk.
    const id = setInterval(() => { if (getMode() === "auto") applyTheme("auto"); }, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, []);

  const cycle = () => { const n = NEXT[mode]; setMode(n); applyTheme(n); };

  return (
    <button
      onClick={cycle}
      title={`Theme: ${mode} (click to change)`}
      className="rounded border border-border px-2 py-1 font-mono text-[11px] uppercase tracking-wider text-textmid transition hover:border-gold hover:text-gold"
    >
      {ICON[mode]} {mode}
    </button>
  );
}
