import { ExternalLink, Info } from "lucide-react";
import type { ClaimSearchResult, SourceType } from "@/types";

const TYPE_LABEL: Record<SourceType, { label: string; cls: string }> = {
  government: { label: "Government", cls: "bg-blue-50 text-blue-700" },
  institution: { label: "Institution", cls: "bg-blue-50 text-blue-700" },
  research: { label: "Research", cls: "bg-indigo-50 text-indigo-700" },
  news: { label: "News", cls: "bg-sky-50 text-sky-700" },
  reference: { label: "Reference", cls: "bg-slate-100 text-slate-600" },
  web: { label: "Web", cls: "bg-slate-100 text-slate-600" },
  community: { label: "Blog / forum", cls: "bg-orange-50 text-orange-700" },
};

function isSafeUrl(url: string) {
  return /^https?:\/\//i.test(url);
}

export default function EvidencePanel({ result }: { result: ClaimSearchResult }) {
  return (
    <div className="mt-3 space-y-3 border-t border-slate-100 pt-3">
      {result.search_query && (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Search query {result.query_source === "rule_based" && "(automatic)"}
          </p>
          <p className="mt-0.5 break-words text-sm text-slate-700">{result.search_query}</p>
        </div>
      )}

      {result.sources.length === 0 ? (
        <p className="text-sm text-slate-500">
          {result.search_status === "failed" || result.search_status === "skipped"
            ? (result.error?.message ?? "This claim was not searched.")
            : "No relevant sources were found for this query."}
        </p>
      ) : (
        <ul className="space-y-2">
          {result.sources.map((s) => (
            <li key={s.url} className="rounded-xl border border-slate-100 bg-slate-50/50 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${TYPE_LABEL[s.source_type].cls}`}>
                  {TYPE_LABEL[s.source_type].label}
                </span>
                <span className="text-xs text-slate-500">{s.domain}</span>
                {s.published_date && <span className="text-xs text-slate-400">· {s.published_date}</span>}
              </div>
              {isSafeUrl(s.url) ? (
                <a
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="mt-1 inline-flex items-start gap-1 break-words text-sm font-semibold text-navy-800 hover:text-sky-brand hover:underline"
                >
                  {s.title}
                  <ExternalLink className="mt-1 h-3 w-3 shrink-0" />
                </a>
              ) : (
                <span className="mt-1 block text-sm font-semibold text-navy-800">{s.title}</span>
              )}
              {s.content && <p className="mt-1 line-clamp-4 break-words text-xs leading-relaxed text-slate-600">{s.content}</p>}
            </li>
          ))}
        </ul>
      )}

      <p className="flex items-start gap-1.5 text-[11px] text-slate-400">
        <Info className="mt-0.5 h-3 w-3 shrink-0" />
        Web excerpts are unverified and are not proof. They are collected for the fact-checking step.
      </p>
    </div>
  );
}
