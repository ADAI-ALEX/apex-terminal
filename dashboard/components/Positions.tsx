"use client";

import type { PositionView } from "@/lib/types";

export function Positions({ positions }: { positions: PositionView[] }) {
  return (
    <div className="rounded-md border border-border bg-bg2">
      <div className="border-b border-border px-4 py-3 font-mono text-[10px] uppercase tracking-wider text-gold">
        // Open Positions ({positions.length})
      </div>
      {positions.length === 0 ? (
        <div className="px-4 py-8 text-center font-mono text-xs text-textdim">
          No open positions.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="font-mono text-[10px] uppercase tracking-wider text-textdim">
                {["Market", "Dir", "Size", "Entry", "Now", "Stop", "Target", "P&L", "Strategy", "Conf"].map(
                  (h) => (
                    <th key={h} className="px-3 py-2 font-medium">
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.deal_id} className="border-t border-border">
                  <td className="px-3 py-2 font-medium">{p.market_key}</td>
                  <td className={`px-3 py-2 ${p.direction === "BUY" ? "text-up" : "text-down"}`}>
                    {p.direction}
                  </td>
                  <td className="px-3 py-2 text-textmid">£{p.size.toFixed(2)}</td>
                  <td className="px-3 py-2 text-textmid">{p.entry_price}</td>
                  <td className="px-3 py-2 text-textmid">{p.current_price}</td>
                  <td className="px-3 py-2 text-textmid">{p.stop_price}</td>
                  <td className="px-3 py-2 text-textmid">{p.target_price}</td>
                  <td className={`px-3 py-2 font-bold ${p.unrealised_pnl >= 0 ? "text-up" : "text-down"}`}>
                    £{p.unrealised_pnl.toFixed(2)}
                    <span className="ml-1 font-normal text-textdim">
                      ({p.unrealised_points >= 0 ? "+" : ""}
                      {p.unrealised_points}pt)
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono text-[10px] text-textmid">{p.strategy}</td>
                  <td className="px-3 py-2 text-textmid">{(p.confidence * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
