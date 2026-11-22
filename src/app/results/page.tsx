"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { FileSearch, Upload } from "lucide-react";
import ResultsDashboard from "@/components/ResultsDashboard";
import EmptyState from "@/components/EmptyState";
import { recallReport, rememberReport } from "@/lib/lastReport";

function ResultsContent() {
  const params = useSearchParams();
  const fromUrl = params.get("file");
  const [fileId, setFileId] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    if (fromUrl) {
      rememberReport(fromUrl);
      setFileId(fromUrl);
    } else {
      setFileId(recallReport());
    }
  }, [fromUrl]);

  if (fileId === undefined) return <div className="h-40 animate-pulse rounded-2xl bg-slate-100" role="status" aria-label="Loading" />;

  if (!fileId) {
    return (
      <EmptyState
        icon={<FileSearch className="h-6 w-6" />}
        title="No results yet"
        description="Upload a PDF, extract its claims, search the web for evidence and verify them. The results will appear here."
        action={
          <div className="flex flex-wrap justify-center gap-2">
            <Link href="/dashboard" className="inline-flex items-center gap-2 rounded-xl bg-navy-900 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-700">
              <Upload className="h-4 w-4" /> Upload a PDF
            </Link>
            <Link href="/results/demo" className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-navy-900 hover:bg-slate-50">
              Preview with demo data
            </Link>
          </div>
        }
      />
    );
  }

  return <ResultsDashboard key={fileId} fileId={fileId} />;
}

export default function ResultsPage() {
  return (
    <Suspense fallback={<div className="h-40 animate-pulse rounded-2xl bg-slate-100" />}>
      <ResultsContent />
    </Suspense>
  );
}
