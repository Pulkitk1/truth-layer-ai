import { ExternalLink, MousePointerClick, X } from "lucide-react";
import type { Claim } from "@/types";
import StatusBadge from "./StatusBadge";

interface ClaimDetailPanelProps {
  claim: Claim | null;
  onClose: () => void;
}

export default function ClaimDetailPanel({ claim, onClose }: ClaimDetailPanelProps) {
  if (!claim) {
    return (
      <div className="flex h-full min-h-64 flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50/50 p-6 text-center">
        <MousePointerClick className="h-6 w-6 text-slate-400" />
        <p className="mt-3 text-sm text-slate-500">
          Select a claim to see its evidence and sources.
        </p>
      </div>
    );
  }

  return (
    <aside className="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <StatusBadge status={claim.status} />
        <button onClick={onClose} aria-label="Close details" className="text-slate-400 hover:text-slate-700">
          <X className="h-4 w-4" />
        </button>
      </div>
      <p className="mt-3 text-sm font-semibold text-navy-900">{claim.text}</p>
      <p className="mt-1 text-xs text-slate-500">
        Page {claim.page} · Confidence {claim.confidence}%
      </p>

      <h4 className="mt-5 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Evidence
      </h4>
      <p className="mt-1 text-sm text-slate-600">{claim.explanation}</p>

      {claim.correction && (
        <>
          <h4 className="mt-5 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Suggested correction
          </h4>
          <p className="mt-1 rounded-xl bg-orange-50 p-3 text-sm text-slate-700">
            {claim.correction}
          </p>
        </>
      )}

      <h4 className="mt-5 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Sources
      </h4>
      {claim.sources.length === 0 ? (
        <p className="mt-1 text-sm text-slate-500">[DEMO] No sources found.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {claim.sources.map((s) => (
            <li key={s.url} className="rounded-xl border border-slate-100 p-3">
              <span className="flex items-center gap-1.5 text-sm font-medium text-navy-900">
                {s.title}
                <ExternalLink className="h-3 w-3 text-slate-400" />
              </span>
              <p className="mt-1 text-xs text-slate-500">{s.snippet}</p>
              <p className="mt-1 truncate text-xs text-sky-brand">{s.url}</p>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-4 text-[11px] font-semibold text-slate-400">
        DEMO DATA – not a real fact-check.
      </p>
    </aside>
  );
}
