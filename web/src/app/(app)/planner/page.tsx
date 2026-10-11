"use client";

import { useAppNavigate } from "@/lib/routes";
import Planner from "@/screens/Planner";

export default function PlannerPage() {
  const navigate = useAppNavigate();
  return <Planner navigate={navigate} />;
}
