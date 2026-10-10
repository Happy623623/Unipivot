"use client";

import { useAppNavigate } from "@/lib/routes";
import Settings from "@/screens/Settings";

export default function SettingsPage() {
  const navigate = useAppNavigate();
  return <Settings navigate={navigate} />;
}
