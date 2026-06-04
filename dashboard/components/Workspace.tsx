"use client";

import { useState } from "react";
import { Terminal } from "./Terminal";
import { BacktestTab } from "./BacktestTab";

type Tab = "terminal" | "backtest";

/**
 * Top-level workspace tabs. "Terminal" is the live dashboard; "Backtest" runs the
 * strategy book over historical data. (A dockable/zoomable grid is the next iteration.)
 */
export function Workspace() {
  const [tab, setTab] = useState<Tab>("terminal");

  return (
    <div>
      <nav className="mb-4 flex gap-1 border-b border-border">
        <TopTab active={tab === "terminal"} onClick={() => setTab("terminal")}>Terminal</TopTab>
        <TopTab active={tab === "backtest"} onClick={() => setTab("backtest")}>Algorithms</TopTab>
      </nav>
      {tab === "terminal" ? <Terminal /> : <BacktestTab />}
    </div>
  );
}

function TopTab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`-mb-px border-b-2 px-5 py-2 font-mono text-[11px] uppercase tracking-wider transition ${
        active ? "border-gold text-gold" : "border-transparent text-textdim hover:text-textmid"
      }`}
    >
      {children}
    </button>
  );
}
