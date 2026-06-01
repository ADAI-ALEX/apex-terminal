"use client";

import { signOut } from "next-auth/react";

export function SignOutButton() {
  return (
    <button
      type="button"
      onClick={() => {
        if (confirm("Sign out of Apex Algo?")) {
          void signOut({ callbackUrl: "/login" });
        }
      }}
      className="rounded border border-border px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-textmid transition hover:border-gold hover:text-gold"
    >
      Sign out
    </button>
  );
}
