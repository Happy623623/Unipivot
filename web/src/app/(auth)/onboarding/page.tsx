"use client";

import { useRouter } from "next/navigation";
import Onboarding from "@/screens/Onboarding";

export default function OnboardingPage() {
  const router = useRouter();
  return <Onboarding onDone={() => router.replace("/")} />;
}
