"use client";

import { useAppNavigate } from "@/lib/routes";
import Documents from "@/screens/Documents";

export default function DocumentsPage() {
  const navigate = useAppNavigate();
  return <Documents navigate={navigate} />;
}
