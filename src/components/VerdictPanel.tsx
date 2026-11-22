import { ExternalLink, Info } from "lucide-react";
import type { VerdictSource, VerificationResult } from "@/types";

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

function SourceList({ title, sources, tone }: { title: string; sources: VerdictSource[]; tone: string }) {
  if (sources.length === 0) return null;
  return (
    <div>
      <h4 className={`text-[11px] font-semibold uppercase tracking-wide ${tone}`}>
        {title} ({sources.length})
      </h4>
      <ul className="mt-1.5 space-y-2">
        {sources.map((s) => (
          <li key={s.url} className="rounded-xl border border-slate-100 bg-slate-50/50 p-3">
            <div className="flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
              <span className="font-medium">{s.domain}</span>
              {s.published_date && <span className="text-slate-400">· {s.published_date}</span>}
            </div>
            {/^https?:\/\//i.test(s.url) ? (
              <a
                href={s.url}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="mt-0.5 inline-flex items-start gap-1 break-words text-sm font-semibold text-navy-800 hover:text-sky-brand hover:underline"
              >
                {s.title}
                <ExternalLink className="mt-1 h-3 w-3 shrink-0" />
              </a>
            ) : (
              <span className="text-sm font-semibold text-navy-800">{s.title}</span>
            )}
            {s.relevance && <p className="mt-1 text-xs text-slate-600">{s.relevance}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Verdict body: reasoning, correction, confidence, and the sources the AI relied on. */
export default function VerdictPanel({ result, detailsOpen }: { result: VerificationResult; detailsOpen: boolean }) {
  const status = result.verification_status ?? "UNVERIFIED";
  const conf = result.confidence_score ?? 0;

  return (
    <div className="mt-3 space-y-3 border-t border-slate-100 pt-3">
      <p className="text-sm leading-relaxed text-slate-700">{result.explanation}</p>

      {NOTE[result.claim_type] && (
        <p className="flex items-start gap-1.5 rounded-lg bg-slate-50 p-2.5 text-xs text-slate-600">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {NOTE[result.claim_type]}
        </p>
      )}

      {result.corrected_claim && (
        <div className="rounded-xl bg-orange-50 p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-orange-700">Corrected information</p>
          <p className="mt-1 text-sm text-slate-800">{result.corrected_claim}</p>
        </div>
      )}

      <div>
        <div className="flex items-center justify-between text-xs text-slate-500">
          <span title="How strong the available evidence is. Not a statistical probability.">Evidence strength</span>
          <span className="font-semibold text-navy-900">{conf}/100</span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200">
          <div className={`h-full rounded-full ${BAR[status]}`} style={{ width: `${conf}%` }} />
        </div>
      </div>

      {detailsOpen && (
        <div className="space-y-3">
          {result.evidence_summary && (
            <div>
              <h4 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Evidence summary</h4>
              <p className="mt-1 text-sm text-slate-600">{result.evidence_summary}</p>
            </div>
          )}
          <SourceList title="Supporting evidence" sources={result.supporting_sources} tone="text-green-700" />
          <SourceList title="Contradicting evidence" sources={result.contradicting_sources} tone="text-red-700" />
          {result.supporting_sources.length === 0 && result.contradicting_sources.length === 0 && (
            <p className="text-sm text-slate-500">
              No collected source was cited as supporting or contradicting this claim ({result.sources_considered}{" "}
              reviewed).
            </p>
          )}
          {result.adjustments.length > 0 && (
            <ul className="space-y-1 rounded-lg bg-orange-50 p-2.5 text-xs text-orange-800">
              {result.adjustments.map((a) => (
                <li key={a}>Safety rule: {a}</li>
              ))}
            </ul>
          )}
          <p className="text-[11px] text-slate-400">
            AI-assisted result based only on the web excerpts collected for this claim. Review the sources before relying
            on it.
          </p>
        </div>
      )}
    </div>
  );
}
