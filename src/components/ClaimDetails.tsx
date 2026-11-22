"use client";

import { Calendar, ExternalLink, Info, MousePointerClick, ThumbsDown, ThumbsUp, X } from "lucide-react";
import StatusBadge from "./StatusBadge";
import { badgeStatus, categoryLabel } from "@/lib/report";
import type { EvidenceSourceItem, ReportClaim, VerdictSource } from "@/types";

const BAR: Record<string, string> = {
  VERIFIED: "bg-green-500",
  INACCURATE: "bg-orange-500",
  FALSE: "bg-red-500",
  UNVERIFIED: "bg-slate-400",
};

const NOTE: Record<string, string> = {
  prediction: "This is a forecast, so it can’t be confirmed or refuted as a fact.",
  hypothetical: "This looks like a hypothetical or illustrative example, not a real-world event.",
  not_verifiable: "This statement isn’t objectively verifiable.",
};

const safe = (url: string) => /^https?:\/\//i.test(url);

function SourceCard({
  title,
  url,
  domain,
  date,
  note,
  tone,
}: {
  title: string;
  url: string;
  domain: string;
  date: string | null;
  note?: string;
  tone: "support" | "contradict" | "neutral";
}) {
  const border = { support: "border-l-green-500", contradict: "border-l-red-500", neutral: "border-l-slate-300" }[tone];
  return (
    <li className={`rounded-xl border border-slate-100 border-l-4 ${border} bg-white p-3`}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-500">
        <span className="font-medium">{domain}</span>
        {date && (
          <span className="inline-flex items-center gap-1 text-slate-400">
            <Calendar className="h-3 w-3" />
            {date}
          </span>
        )}
      </div>
      {safe(url) ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="mt-0.5 inline-flex items-start gap-1 break-words text-sm font-semibold text-navy-800 hover:text-sky-brand hover:underline"
        >
          {title}
          <ExternalLink className="mt-1 h-3 w-3 shrink-0" />
        </a>
      ) : (
        <span className="mt-0.5 block text-sm font-semibold text-navy-800">{title}</span>
      )}
      {note && <p className="mt-1 break-words text-xs leading-relaxed text-slate-600">{note}</p>}
    </li>
  );
}

function Group({
  label,
  icon,
  tone,
  headColor,
  sources,
  empty,
}: {
  label: string;
  icon: React.ReactNode;
  tone: "support" | "contradict";
  headColor: string;
  sources: VerdictSource[];
  empty: string;
}) {
  return (
    <section aria-label={label}>
      <h4 className={`flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide ${headColor}`}>
        {icon} {label} ({sources.length})
      </h4>
      {sources.length === 0 ? (
        <p className="mt-1.5 text-sm text-slate-400">{empty}</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {sources.map((s) => (
            <SourceCard key={s.url} title={s.title} url={s.url} domain={s.domain} date={s.published_date} note={s.relevance} tone={tone} />
          ))}
        </ul>
      )}
    </section>
  );
}

export function DetailsPlaceholder() {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50/50 p-6 text-center">
      <MousePointerClick className="h-6 w-6 text-slate-400" />
      <p className="mt-3 text-sm text-slate-500">Select a claim to see its verdict, explanation and evidence.</p>
    </div>
  );
}

export default function ClaimDetails({ claim, onClose }: { claim: ReportClaim; onClose: () => void }) {
  const v = claim.verification;
  const b = badgeStatus(claim.status);
  const cited = new Set([...(v?.supporting_sources ?? []), ...(v?.contradicting_sources ?? [])].map((s) => s.url));
  const others: EvidenceSourceItem[] = claim.collected_sources.filter((s) => !cited.has(s.url));

  return (
    <aside aria-label="Claim details" className="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {b ? (
            <StatusBadge status={b} />
          ) : (
            <span className="rounded-full bg-slate-50 px-2.5 py-0.5 text-xs font-semibold text-slate-500 ring-1 ring-inset ring-slate-300/50">
              Not verified yet
            </span>
          )}
          <span className="text-xs text-slate-400">{claim.claim_id}</span>
        </div>
        <button onClick={onClose} aria-label="Close details" className="rounded-lg p-1 text-slate-400 hover:bg-slate-50 hover:text-slate-700">
          <X className="h-4 w-4" />
        </button>
      </div>

      <section className="mt-4">
        <h4 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Original claim</h4>
        <p className="mt-1 text-sm font-semibold leading-relaxed text-navy-900">“{claim.claim_text}”</p>
        <p className="mt-1.5 text-xs text-slate-500">
          PDF page {claim.page_number} · {categoryLabel(claim.category)}
          {claim.value && <> · value {claim.value}</>}
          {claim.unit && <> {claim.unit}</>}
          {claim.time_period && <> · {claim.time_period}</>}
        </p>
      </section>

      {v ? (
        <>
          <section className="mt-5">
            <h4 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">AI explanation</h4>
            <p className="mt-1 text-sm leading-relaxed text-slate-700">{v.explanation}</p>
            {NOTE[v.claim_type] && (
              <p className="mt-2 flex items-start gap-1.5 rounded-lg bg-slate-50 p-2.5 text-xs text-slate-600">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {NOTE[v.claim_type]}
              </p>
            )}
          </section>

          {v.corrected_claim && (
            <section className="mt-4 rounded-xl bg-orange-50 p-3">
              <h4 className="text-[11px] font-semibold uppercase tracking-wide text-orange-700">Corrected claim</h4>
              <p className="mt-1 text-sm text-slate-800">{v.corrected_claim}</p>
            </section>
          )}

          <section className="mt-4" aria-label="Confidence">
            <div className="flex items-center justify-between text-xs text-slate-500">
              <span title="How strong the available evidence is. Not a statistical probability.">Confidence (evidence strength)</span>
              <span className="font-semibold text-navy-900">{claim.confidence_score}/100</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200">
              <div className={`h-full rounded-full ${BAR[claim.status] ?? "bg-slate-400"}`} style={{ width: `${claim.confidence_score ?? 0}%` }} />
            </div>
          </section>

          {v.evidence_summary && (
            <section className="mt-4">
              <h4 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Evidence summary</h4>
              <p className="mt-1 text-sm text-slate-600">{v.evidence_summary}</p>
            </section>
          )}

          <div className="mt-5 space-y-4">
            <Group
              label="Supporting evidence"
              icon={<ThumbsUp className="h-3.5 w-3.5" />}
              tone="support"
              headColor="text-green-700"
              sources={v.supporting_sources}
              empty="No collected source was cited as supporting this claim."
            />
            <Group
              label="Contradicting evidence"
              icon={<ThumbsDown className="h-3.5 w-3.5" />}
              tone="contradict"
              headColor="text-red-700"
              sources={v.contradicting_sources}
              empty="No collected source was cited as contradicting this claim."
            />
          </div>

          {v.adjustments.length > 0 && (
            <ul className="mt-4 space-y-1 rounded-lg bg-orange-50 p-2.5 text-xs text-orange-800">
              {v.adjustments.map((a) => (
                <li key={a}>Safety rule: {a}</li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <section className="mt-5 rounded-xl bg-slate-50 p-3 text-sm text-slate-600">
          {claim.stale
            ? "The collected evidence changed after this claim was verified, so the old verdict is hidden. Verify the claim again from the Dashboard page."
            : "This claim has not been fact-checked yet. Run “Search Web for Evidence” and “Verify All Claims” from the Dashboard page."}
        </section>
      )}

      {others.length > 0 && (
        <details className="mt-5 group">
          <summary className="cursor-pointer text-xs font-semibold text-sky-brand hover:underline">
            Other collected sources ({others.length})
          </summary>
          <p className="mt-1 text-[11px] text-slate-400">Found by the web search but not cited in the verdict. Excerpts are unverified.</p>
          <ul className="mt-2 space-y-2">
            {others.map((s) => (
              <SourceCard key={s.url} title={s.title} url={s.url} domain={s.domain} date={s.published_date} note={s.content} tone="neutral" />
            ))}
          </ul>
        </details>
      )}

      <p className="mt-5 text-[11px] text-slate-400">
        AI-assisted result based only on the web excerpts collected for this claim. Review the sources before relying on it.
      </p>
    </aside>
  );
}
