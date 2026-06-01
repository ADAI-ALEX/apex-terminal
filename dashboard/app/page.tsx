import Link from "next/link";
import { auth } from "@/auth";
import { Dashboard } from "@/components/Dashboard";
import { OnboardingGate } from "@/components/OnboardingGate";
import { SignOutButton } from "@/components/SignOutButton";

export default async function Page() {
  const session = await auth();

  return (
    <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-8">
      <header className="mb-6 flex items-center justify-between border-b border-border pb-4">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.3em] text-gold">
            ADAI Systems · Command Centre
          </div>
          <h1 className="text-2xl font-bold">Apex Algo</h1>
        </div>
        <div className="flex items-center gap-4">
          <span className="hidden font-mono text-xs text-textmid sm:inline">
            {session?.user?.name}
          </span>
          <Link
            href="/settings"
            className="rounded border border-border px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-textmid transition hover:border-gold hover:text-gold"
          >
            Settings
          </Link>
          <SignOutButton />
        </div>
      </header>

      <OnboardingGate>
        <Dashboard />
      </OnboardingGate>
    </main>
  );
}
