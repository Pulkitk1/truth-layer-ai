import Link from "next/link";
import { FileClock } from "lucide-react";
import UploadWorkspace from "@/components/UploadWorkspace";
import EmptyState from "@/components/EmptyState";
import type { Report } from "@/types";

// No reports exist yet: report storage arrives in a later step.
const recentReports: Report[] = [];

export default function DashboardPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-navy-900 sm:text-3xl">Welcome back 👋</h1>
        <p className="mt-1 text-slate-500">
          Upload a PDF to start verifying its claims.
        </p>
      </div>

      <UploadWorkspace />

      <section id="reports" className="scroll-mt-20">
        <h2 className="mb-3 text-lg font-semibold text-navy-900">Recent reports</h2>
        {recentReports.length === 0 ? (
          <EmptyState
            icon={<FileClock className="h-6 w-6" />}
            title="No reports yet"
            description="Once you analyze a document, its fact-checking report will appear here."
            action={
              <Link
                href="/results/demo"
                className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-navy-900 shadow-sm hover:bg-slate-50"
              >
                Preview a demo report
              </Link>
            }
          />
        ) : (
          <ul className="space-y-2">
            {recentReports.map((r) => (
              <li key={r.id} className="rounded-xl border border-slate-100 bg-white p-4">
                {r.fileName}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
