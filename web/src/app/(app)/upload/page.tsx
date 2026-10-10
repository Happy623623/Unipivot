"use client";

import { useAppNavigate } from "@/lib/routes";
import PosterUpload from "@/screens/PosterUpload";

export default function UploadPage() {
  const navigate = useAppNavigate();
  return <PosterUpload navigate={navigate} />;
}
