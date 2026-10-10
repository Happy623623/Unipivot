"use client";

import { useAppNavigate } from "@/lib/routes";
import Academics from "@/screens/Academics";

export default function AcademicsPage() {
  const navigate = useAppNavigate();
  return <Academics navigate={navigate} />;
}
