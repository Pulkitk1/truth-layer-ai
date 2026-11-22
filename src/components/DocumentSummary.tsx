"use client";

import { AlertCircle, ClipboardList, Loader2, RefreshCw, Sparkles } from "lucide-react";
import StatusBadge from "./StatusBadge";
import { badgeStatus } from "@/lib/report";
import type { ReportSummary } from "@/types";

interface Props {
  summary: ReportSummary;
  generating: boolean;
  canGenerate: boolean;
  onRegenerate: () => void;
  onOpenClaim: (claimId: string) => void;
}

/** The built-in summary is computed from the stored verdicts; the AI narrative only rephrases the same results. */
export default function DocumentSummary({ summary, generating, canGenerate, onRegenerate, onOpenClaim }: Props) {
  return (
    <section className="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm" aria-label="Document summary">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-navy-900">
          <ClipboardList className="h-4 w-4 text-sky-brand" /> Document summary
        </h3>
        {canGenerate && (
          <button
            onClick={onRegenerate}
            disabled={generating}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-navy-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : summary.narrative ? <RefreshCw className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
            {generating ? "Writing…" : summary.narrative ? "Regenerate" : "Write AI summary"}
          </button>
        )}
      </div>

      <p className="mt-3 text-sm leading-relaxed text-slate-700">{summary.text}</p>

      {generating && !summary.narrative && (
        <div className="mt-4 space-y-2" role="status" aria-label="Writing AI summary">
          <div className="h-3 w-full animate-pulse rounded bg-slate-100" />
          <div className="h-3 w-5/6 animate-pulse rounded bg-slate-100" />
          <div className="h-3 w-2/3 animate-pulse rounded bg-slate-100" />
        </div>
      )}

      {summary.narrative && (
        <div className="mt-4 rounded-xl bg-blue-50/60 p-4">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-sky-brand">
            <Sparkles className="h-3 w-3" /> AI-written summary
            {summary.narrative_model && <span className="font-normal normal-case text-slate-400">· {summary.narrative_model}</span>}
          </p>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-700">{summary.narrative}</p>
          <p className="mt-2 text-[11px] text-slate-400">Written from the results above; it adds no new findings.</p>
        </div>
      )}

      {!generating && summary.narrative_error && !summary.narrative && canGenerate && (
        <p className="mt-3 flex items-start gap-1.5 text-xs text-slate-500">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          AI summary unavailable: {summary.narrative_error}
        </p>
      )}

      <div className="mt-5">
        <h4 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          Needs further investigation ({summary.needs_investigation.length})
        </h4>
        {summary.needs_investigation.length === 0 ? (
          <p className="mt-1.5 text-sm text-slate-500">No claims are flagged for follow-up.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {summary.needs_investigation.map((i) => {
              const b = badgeStatus(i.status);
              return (
                <li key={i.claim_id}>
                  <button
                    onClick={() => onOpenClaim(i.claim_id)}
                    className="flex w-full min-w-0 flex-col items-start gap-1.5 rounded-xl border border-slate-100 p-3 text-left hover:bg-slate-50 sm:flex-row sm:items-center sm:justify-between sm:gap-3"
                  >
                    <span className="min-w-0 max-w-full flex-1">
                      <span className="line-clamp-2 block break-words text-sm font-medium text-navy-900">{i.claim_text}</span>
                      <span className="block text-xs text-slate-500">{i.reason}</span>
                    </span>
                    {b ? (
                      <StatusBadge status={b} />
                    ) : (
                      <span className="shrink-0 rounded-full bg-slate-50 px-2.5 py-0.5 text-xs font-semibold text-slate-500 ring-1 ring-inset ring-slate-300/50">
                        Not verified yet
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
