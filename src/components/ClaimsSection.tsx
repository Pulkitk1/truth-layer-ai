"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Clock,
  Globe2,
  Loader2,
  RefreshCw,
  Scale,
  Search,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { extractClaims, searchClaims, verifyClaims } from "@/lib/api";
import { rememberReport } from "@/lib/lastReport";
import StatCard from "./StatCard";
import EmptyState from "./EmptyState";
import ClaimCard, { type SearchState, type VerifyState } from "./ClaimCard";
import VerificationSummary, { type VerdictFilter } from "./VerificationSummary";
import type { ClaimsResult } from "@/types";

const SEARCH_CONCURRENCY = 3;
// One at a time: Groq limits tokens per minute, and each fact-check sends a few thousand tokens.
const VERIFY_CONCURRENCY = 1;
// Errors that would hit every remaining claim too, so the batch stops instead of failing them one by one.
const COMMON_STOP = ["network", "file_not_found", "claims_not_extracted", "evidence_not_collected"];
const SEARCH_STOP = [...COMMON_STOP, "tavily_not_configured", "tavily_auth_failed", "tavily_credits_exhausted", "tavily_forbidden"];
const VERIFY_STOP = [...COMMON_STOP, "groq_not_configured", "groq_auth_failed", "groq_rate_limited", "groq_daily_limit", "groq_model_not_found"];

const STEPS = [
  { at: 0, text: "Preparing document text…" },
  { at: 2, text: "Sending to Groq AI…" },
  { at: 6, text: "AI is identifying factual claims…" },
  { at: 25, text: "Still working. Long documents are processed in sections…" },
];

function ErrorBox({ title, message }: { title: string; message: string }) {
  return (
    <div className="mt-3 flex items-start gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700" role="alert">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        <p className="font-semibold">{title}</p>
        <p className="mt-0.5">{message}</p>
      </div>
    </div>
  );
}

function Progress({ label, right, pct, color }: { label: string; right: string; pct: number; color: string }) {
  return (
    <div className="mt-3" role="status">
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>{label}</span>
        <span>{right}</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function ClaimsSection({ fileId }: { fileId: string }) {
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ClaimsResult | null>(null);

  const [search, setSearch] = useState<Record<string, SearchState>>({});
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [verify, setVerify] = useState<Record<string, VerifyState>>({});
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [filter, setFilter] = useState<VerdictFilter>("all");

  const cancelRef = useRef(false);

  useEffect(() => {
    if (!loading) return;
    setElapsed(0);
    const t = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(t);
  }, [loading]);

  useEffect(() => () => void (cancelRef.current = true), []);

  const run = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setSearch({});
    setSearchError(null);
    setVerify({});
    setVerifyError(null);
    setFilter("all");
    try {
      setResult(await extractClaims(fileId));
      rememberReport(fileId); // lets /results reopen this document
    } catch (e) {
      setError(e instanceof Error ? e.message : "Claim extraction failed.");
    } finally {
      setLoading(false);
    }
  };

  /** Search claims one request each (3 at a time) so the UI can show real per-claim progress. */
  const runSearch = async (refresh = false) => {
    if (!result) return;
    const todo = result.claims.filter((c) => {
      const s = search[c.claim_id];
      return refresh || !s || s.phase !== "done" || s.result.search_status === "failed" || s.result.search_status === "skipped";
    });
    if (todo.length === 0) return;

    cancelRef.current = false;
    setSearching(true);
    setSearchError(null);
    setSearch((prev) => {
      const next = { ...prev };
      todo.forEach((c) => (next[c.claim_id] = { phase: "waiting" }));
      return next;
    });
    // New evidence makes earlier verdicts for these claims stale.
    setVerify((prev) => {
      const next = { ...prev };
      todo.forEach((c) => delete next[c.claim_id]);
      return next;
    });

    const queue = [...todo];
    let stop: string | null = null;

    const worker = async () => {
      while (queue.length && !stop && !cancelRef.current) {
        const claim = queue.shift()!;
        setSearch((p) => ({ ...p, [claim.claim_id]: { phase: "searching" } }));
        try {
          const res = await searchClaims(fileId, { claimIds: [claim.claim_id], refresh });
          setSearch((p) => ({ ...p, [claim.claim_id]: { phase: "done", result: res.claims[0] } }));
        } catch (e) {
          const message = e instanceof Error ? e.message : "Search failed.";
          setSearch((p) => ({ ...p, [claim.claim_id]: { phase: "failed", message } }));
          if (SEARCH_STOP.includes((e as { code?: string }).code ?? "")) stop = message;
        }
      }
    };

    await Promise.all(Array.from({ length: SEARCH_CONCURRENCY }, worker));

    if (stop) {
      setSearchError(stop);
      setSearch((p) => {
        const next = { ...p };
        queue.forEach((c) => (next[c.claim_id] = { phase: "failed", message: stop! }));
        return next;
      });
    }
    setSearching(false);
  };

  const hasEvidence = (id: string) => {
    const s = search[id];
    return s?.phase === "done" && (s.result.search_status === "completed" || s.result.search_status === "no_results");
  };

  /** Verify claims one request each (3 at a time) so the UI can show real per-claim progress. */
  const runVerify = async (refresh = false) => {
    if (!result) return;
    const todo = result.claims.filter((c) => {
      if (!hasEvidence(c.claim_id)) return false;
      const v = verify[c.claim_id];
      return refresh || !v || v.phase !== "done";
    });
    if (todo.length === 0) return;

    cancelRef.current = false;
    setVerifying(true);
    setVerifyError(null);
    setVerify((prev) => {
      const next = { ...prev };
      todo.forEach((c) => (next[c.claim_id] = { phase: "idle" }));
      return next;
    });

    const queue = [...todo];
    let stop: string | null = null;

    const worker = async () => {
      while (queue.length && !stop && !cancelRef.current) {
        const claim = queue.shift()!;
        setVerify((p) => ({ ...p, [claim.claim_id]: { phase: "verifying" } }));
        try {
          const res = await verifyClaims(fileId, { claimIds: [claim.claim_id], refresh });
          const r = res.results[0];
          setVerify((p) => ({
            ...p,
            [claim.claim_id]:
              r.check_status === "completed"
                ? { phase: "done", result: r }
                : { phase: "failed", message: r.error?.message ?? "Verification failed." },
          }));
        } catch (e) {
          const message = e instanceof Error ? e.message : "Verification failed.";
          setVerify((p) => ({ ...p, [claim.claim_id]: { phase: "failed", message } }));
          if (VERIFY_STOP.includes((e as { code?: string }).code ?? "")) stop = message;
        }
      }
    };

    await Promise.all(Array.from({ length: VERIFY_CONCURRENCY }, worker));

    if (stop) {
      setVerifyError(stop);
      setVerify((p) => {
        const next = { ...p };
        queue.forEach((c) => (next[c.claim_id] = { phase: "failed", message: stop! }));
        return next;
      });
    }
    setVerifying(false);
  };

  const status = [...STEPS].reverse().find((s) => elapsed >= s.at)?.text;

  // ----- derived search state -----
  const claims = result?.claims ?? [];
  const states = claims.map((c) => search[c.claim_id] ?? ({ phase: "waiting" } as SearchState));
  const searchedCount = states.filter((s) => s.phase === "done" || s.phase === "failed").length;
  const anySearched = Object.keys(search).length > 0;
  const sourcesFound = states.reduce((n, s) => n + (s.phase === "done" ? s.result.sources_found : 0), 0);
  const searchFailed = states.filter(
    (s) => s.phase === "failed" || (s.phase === "done" && ["failed", "skipped"].includes(s.result.search_status)),
  ).length;

  // ----- derived verification state -----
  const vStates = claims.map((c) => verify[c.claim_id] ?? ({ phase: "idle" } as VerifyState));
  const verdicts = vStates.flatMap((v) => (v.phase === "done" ? [v.result] : []));
  const anyVerified = Object.keys(verify).length > 0;
  const verifyProgress = vStates.filter((v) => v.phase === "done" || v.phase === "failed").length;
  const verifyFailed = vStates.filter((v) => v.phase === "failed").length;
  const eligible = claims.filter((c) => hasEvidence(c.claim_id)).length;
  const counts = {
    total: result?.total_claims ?? 0,
    verified: verdicts.filter((r) => r.verification_status === "VERIFIED").length,
    inaccurate: verdicts.filter((r) => r.verification_status === "INACCURATE").length,
    false: verdicts.filter((r) => r.verification_status === "FALSE").length,
    unverified: verdicts.filter((r) => r.verification_status === "UNVERIFIED").length,
  };
  const visible = claims.filter((_, i) => {
    if (filter === "all") return true;
    const v = vStates[i];
    return v.phase === "done" && v.result.verification_status?.toLowerCase() === filter;
  });
  const busy = loading || searching || verifying;

  return (
    <section id="claims" className="scroll-mt-20 rounded-2xl border border-slate-100 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-navy-900">AI claim extraction</h2>
          <p className="mt-1 text-sm text-slate-500">
            Find the factual claims in this document, collect web evidence, then fact-check them.
          </p>
        </div>
        <button
          onClick={run}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-xl bg-navy-900 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-navy-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : result ? (
            <RefreshCw className="h-4 w-4" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          {loading ? "Extracting…" : result ? "Run again" : "Extract Claims with AI"}
        </button>
      </div>

      {loading && (
        <div className="mt-5 rounded-xl bg-blue-50 p-4" role="status">
          <p className="flex items-center gap-2 text-sm font-medium text-navy-900">
            <Loader2 className="h-4 w-4 animate-spin text-sky-brand" />
            {status}
          </p>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-blue-100">
            <div className="h-full w-1/3 animate-pulse rounded-full bg-sky-brand" />
          </div>
          <p className="mt-2 text-xs text-slate-500">{elapsed}s elapsed</p>
        </div>
      )}

      {error && (
        <div className="mt-5 flex items-start gap-2 rounded-xl bg-red-50 p-4 text-sm text-red-700" role="alert">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-semibold">Claim extraction failed</p>
            <p className="mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {result && (
        <div className="mt-5 space-y-4">
          {anyVerified && verdicts.length > 0 ? (
            <VerificationSummary counts={counts} filter={filter} onFilter={setFilter} />
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:max-w-xl sm:grid-cols-3">
              <StatCard label="Total claims extracted" value={result.total_claims} />
              <StatCard label="Status" value="Pending" accent="text-slate-500" icon={<Clock className="h-4 w-4" />} />
              {anySearched && (
                <StatCard label="Sources found" value={sourcesFound} accent="text-sky-brand" icon={<Globe2 className="h-4 w-4" />} />
              )}
            </div>
          )}

          {anyVerified && verdicts.length > 0 && (
            <Link
              href={`/results?file=${encodeURIComponent(fileId)}`}
              className="inline-flex items-center gap-2 rounded-xl bg-sky-brand px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-600"
            >
              Open full results dashboard
            </Link>
          )}

          {result.warnings.length > 0 && (
            <div className="flex items-start gap-2 rounded-xl bg-orange-50 p-3 text-sm text-orange-800" role="alert">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <ul className="space-y-1">
                {result.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {claims.length > 0 && (
            <div className="rounded-xl border border-slate-100 bg-slate-50/50 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-navy-900">Web evidence</h3>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Search the live web for sources on each claim. This only collects evidence.
                  </p>
                </div>
                <button
                  onClick={() => runSearch(anySearched && searchFailed === 0)}
                  disabled={busy}
                  className="inline-flex items-center gap-2 rounded-xl bg-sky-brand px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  {searching
                    ? "Searching…"
                    : anySearched
                      ? searchFailed > 0
                        ? "Retry failed searches"
                        : "Search again"
                      : "Search Web for Evidence"}
                </button>
              </div>
              {(searching || anySearched) && (
                <Progress
                  label={`${searching ? "Searching" : "Searched"} ${searchedCount} of ${result.total_claims} claims`}
                  right={`${sourcesFound} sources so far`}
                  pct={(searchedCount / result.total_claims) * 100}
                  color="bg-sky-brand"
                />
              )}
              {searchError && <ErrorBox title="Web search stopped" message={searchError} />}
              {!searching && anySearched && searchFailed > 0 && !searchError && (
                <p className="mt-3 text-xs text-orange-700">
                  {searchFailed} claim(s) could not be searched. Open them to see why, then retry.
                </p>
              )}
            </div>
          )}

          {claims.length > 0 && (
            <div className="rounded-xl border border-slate-100 bg-slate-50/50 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-navy-900">AI fact-check</h3>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {eligible === 0
                      ? "Search the web for evidence first. Claims are checked only against the evidence collected."
                      : "Compares each claim with the collected evidence, one at a time (Groq limits tokens per minute). No new web search is made."}
                  </p>
                </div>
                <button
                  onClick={() => runVerify(anyVerified && verifyFailed === 0)}
                  disabled={busy || eligible === 0}
                  className="inline-flex items-center gap-2 rounded-xl bg-navy-900 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-navy-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {verifying ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scale className="h-4 w-4" />}
                  {verifying
                    ? "Verifying…"
                    : anyVerified
                      ? verifyFailed > 0
                        ? "Retry failed checks"
                        : "Verify again"
                      : "Verify All Claims"}
                </button>
              </div>
              {(verifying || anyVerified) && (
                <Progress
                  label={`${verifying ? "Verifying" : "Verified"} ${verifyProgress} of ${eligible} claims`}
                  right={`${verdicts.length} results`}
                  pct={eligible ? (verifyProgress / eligible) * 100 : 0}
                  color="bg-navy-700"
                />
              )}
              {verifyError && <ErrorBox title="Verification stopped" message={verifyError} />}
              {!verifying && eligible > 0 && eligible < result.total_claims && (
                <p className="mt-3 text-xs text-orange-700">
                  {result.total_claims - eligible} claim(s) have no collected evidence and are not verified. Search for
                  evidence for them first.
                </p>
              )}
            </div>
          )}

          {filter !== "all" && (
            <p className="text-xs text-slate-500">
              Showing {visible.length} {filter} claim(s).{" "}
              <button onClick={() => setFilter("all")} className="font-semibold text-sky-brand hover:underline">
                Show all
              </button>
            </p>
          )}

          {claims.length === 0 ? (
            <EmptyState
              title="No factual claims found"
              description="The AI did not find any objectively verifiable claims in this document."
            />
          ) : (
            <ul className="space-y-3">
              {visible.map((c) => {
                const i = claims.indexOf(c);
                return <ClaimCard key={c.claim_id} claim={c} search={states[i]} verify={vStates[i]} />;
              })}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
