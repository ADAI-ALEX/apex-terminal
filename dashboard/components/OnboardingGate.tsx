"use client";

import { useCallback, useEffect, useState } from "react";
import { getOnboardingStatus, type OnboardingStatus } from "@/lib/onboarding";
import { OnboardingWizard } from "./OnboardingWizard";

/**
 * The unconfigured-launch gate. Reads /onboarding/status; while the algo is not
 * configured it renders the wizard and keeps the dashboard (children) locked.
 * Once onboarding completes it reloads so the SSE stream picks up the live algo.
 */
export function OnboardingGate({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setStatus(await getOnboardingStatus());
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center font-mono text-sm text-textmid">
        Checking system configuration…
      </div>
    );
  }

  if (status?.configured) {
    return <>{children}</>;
  }

  return (
    <div className="space-y-4">
      {status?.mode === "UNREACHABLE" && (
        <div className="rounded-md border border-down/40 bg-down/10 px-4 py-3 text-sm text-down">
          Cannot reach the algo state server. Start it (<span className="font-mono">python main.py</span>)
          or set <span className="font-mono">VPS_URL</span> / <span className="font-mono">VPS_SECRET</span>,
          then you can complete onboarding here.
        </div>
      )}
      <OnboardingWizard
        onComplete={() => {
          // Full reload re-initialises the SSE stream against the now-live algo.
          window.location.reload();
        }}
      />
    </div>
  );
}
