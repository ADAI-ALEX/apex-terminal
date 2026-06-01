"use client";

import { useState } from "react";
import { signOut } from "next-auth/react";

export function SignOutButton() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded border border-border px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-textmid transition hover:border-gold hover:text-gold"
      >
        Sign out
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => !busy && setOpen(false)}
        >
          <div
            className="w-full max-w-sm rounded-md border border-border bg-bg2 p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.3em] text-gold">
              Apex Algo
            </div>
            <h2 className="mb-2 text-lg font-bold">Sign out?</h2>
            <p className="mb-6 text-sm text-textmid">
              You&apos;ll need to log in again. Your trading engine keeps running — this
              only signs you out of the dashboard.
            </p>
            <div className="flex justify-end gap-3">
              <button
                type="button"
                disabled={busy}
                onClick={() => setOpen(false)}
                className="rounded border border-border px-4 py-2 font-mono text-[11px] uppercase tracking-wider text-textmid transition hover:border-gold hover:text-gold disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  void signOut({ callbackUrl: "/login" });
                }}
                className="rounded bg-gold px-4 py-2 text-sm font-bold text-black transition hover:bg-gold2 disabled:opacity-50"
              >
                {busy ? "Signing out…" : "Sign out"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
