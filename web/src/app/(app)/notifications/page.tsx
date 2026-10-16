"use client";

import { useAppNavigate } from "@/lib/routes";
import Notifications from "@/screens/Notifications";

export default function NotificationsPage() {
  const navigate = useAppNavigate();
  return <Notifications navigate={navigate} />;
}
