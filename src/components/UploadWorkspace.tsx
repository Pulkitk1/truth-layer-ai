"use client";

import { useEffect, useState } from "react";
import UploadCard from "./UploadCard";
import ExtractedTextPreview from "./ExtractedTextPreview";
import ClaimsSection from "./ClaimsSection";
import type { ExtractResult } from "@/types";

/** Ties the upload card to the extracted-text preview on the dashboard. */
export default function UploadWorkspace() {
  const [result, setResult] = useState<ExtractResult | null>(null);

  useEffect(() => {
    if (result) document.getElementById("preview")?.scrollIntoView({ behavior: "smooth" });
  }, [result]);

  return (
    <div className="space-y-8">
      <UploadCard onAnalyze={setResult} onReset={() => setResult(null)} />
      {result && <ExtractedTextPreview result={result} />}
      {result && !result.ocr_required && <ClaimsSection key={result.file_id} fileId={result.file_id} />}
    </div>
  );
}
