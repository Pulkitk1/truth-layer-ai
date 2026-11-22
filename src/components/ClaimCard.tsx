"use client";

import { useState } from "react";
import { AlertCircle, ChevronDown, Clock, Globe2, Loader2 } from "lucide-react";
import StatusBadge from "./StatusBadge";
import EvidencePanel from "./EvidencePanel";
import VerdictPanel from "./VerdictPanel";
import type {
  ClaimCategory,
  ClaimSearchResult,
  ExtractedClaim,
  VerificationResult,
} from "@/types";

export const CATEGORY_LABEL: Record<ClaimCategory, string> = {
  statistics: "Statistics",
  financial: "Financial",
  date_timeline: "Date / Timeline",
  market: "Market",
  scientific: "Scientific",
  technical: "Technical",
  company: "Company",
  demographic: "Demographic",
  other: "Other",
};

/** UI state of the web search for one claim. */
export type SearchState =
  | { phase: "waiting" }
  | { phase: "searching" }
  | { phase: "done"; result: ClaimSearchResult }
  | { phase: "failed"; message: string };

/** UI state of the AI verification for one claim. */
export type VerifyState =
  | { phase: "idle" }
  | { phase: "verifying" }
  | { phase: "done"; result: VerificationResult }
  | { phase: "failed"; message: string };

const pill = "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold";

function PendingBadge() {
  return (
    <span className={`${pill} bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-500/20`}>
      <Clock className="h-3 w-3" />
      Pending verification
    </span>
  );
}

function SearchBadge({ state }: { state: SearchState }) {
  if (state.phase === "waiting") return <span className={`${pill} bg-slate-50 text-slate-500`}>Waiting for search</span>;
  if (state.phase === "searching")
    return (
      <span className={`${pill} bg-blue-50 text-blue-700`}>
        <Loader2 className="h-3 w-3 animate-spin" /> Searching…
      </span>
    );
  if (state.phase === "failed" || state.result.search_status === "failed" || state.result.search_status === "skipped")
    return <span className={`${pill} bg-red-50 text-red-700`}>Search failed</span>;
  if (state.result.search_status === "no_results")
    return <span className={`${pill} bg-slate-100 text-slate-600`}>No relevant sources found</span>;
  return (
    <span className={`${pill} bg-blue-50 text-blue-700`}>
      <Globe2 className="h-3 w-3" /> Evidence found · {state.result.sources_found}{" "}
      {state.result.sources_found === 1 ? "source" : "sources"}
    </span>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="mt-0.5 text-sm text-navy-900">{value ?? <span className="text-slate-300">–</span>}</dd>
    </div>
  );
}

export default function ClaimCard({
  claim,
  search,
  verify,
}: {
  claim: ExtractedClaim;
  search: SearchState;
  verify: VerifyState;
}) {
  const [open, setOpen] = useState(false);
  const found = search.phase === "done" ? search.result : null;
  const verdict = verify.phase === "done" ? verify.result : null;
  const status = verdict?.verification_status?.toLowerCase() as "verified" | "inaccurate" | "false" | "unverified" | undefined;
  const canExpand = verdict !== null || found !== null || search.phase === "failed";

  return (
    <li className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-navy-700">
          {CATEGORY_LABEL[claim.category] ?? "Other"}
        </span>
        {status ? <StatusBadge status={status} /> : <PendingBadge />}
      </div>

      <p className="mt-3 text-sm font-medium leading-relaxed text-navy-900">“{claim.claim_text}”</p>
      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Field label="Value" value={claim.value} />
        <Field label="Unit" value={claim.unit} />
        <Field label="Period" value={claim.time_period} />
        <Field label="PDF page" value={String(claim.page_number)} />
      </dl>
      {claim.context && <p className="mt-3 text-xs text-slate-500">{claim.context}</p>}

      {verify.phase === "verifying" && (
        <p className="mt-3 flex items-center gap-1.5 text-xs font-medium text-blue-700" role="status">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> AI is comparing this claim with the evidence…
        </p>
      )}
      {verify.phase === "failed" && (
        <div className="mt-3 flex items-start gap-2 rounded-lg bg-red-50 p-3 text-xs text-red-700" role="alert">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            <span className="font-semibold">Verification failed.</span> {verify.message}
          </p>
        </div>
      )}
      {verdict && <VerdictPanel result={verdict} detailsOpen={open} />}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3">
        <SearchBadge state={search} />
        {canExpand && (
          <button
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            className="inline-flex items-center gap-1 text-xs font-semibold text-sky-brand hover:underline"
          >
            {open ? "Hide evidence" : "Show evidence"}
            <ChevronDown className={`h-3.5 w-3.5 transition ${open ? "rotate-180" : ""}`} />
          </button>
        )}
      </div>

      {open && found && (
        <div className="mt-1">
          <p className="mt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">All sources collected</p>
          <EvidencePanel result={found} />
        </div>
      )}
      {open && search.phase === "failed" && (
        <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{search.message}</p>
      )}
    </li>
  );
}
