import { auth } from "@/auth";
import { Terminal } from "@/components/Terminal";
import { OnboardingGate } from "@/components/OnboardingGate";

export default async function Page() {
  await auth(); // route is gated by middleware; ensures a session context

  // The Terminal is a full-screen shell (its own top bar, sidebar with Settings +
  // Sign out, and bottom workspace tabs). The gate shows onboarding until configured.
  return (
    <OnboardingGate>
      <Terminal />
    </OnboardingGate>
  );
}
