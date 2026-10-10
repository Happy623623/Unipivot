"use client";

import { useAppNavigate } from "@/lib/routes";
import Home from "@/screens/Home";

export default function HomePage() {
  const navigate = useAppNavigate();
  return <Home navigate={navigate} />;
}
