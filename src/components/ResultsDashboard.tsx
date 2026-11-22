"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Download,
  FileText,
  HelpCircle,
  ListChecks,
  Loader2,
  RefreshCw,
  Upload,
  X,
  XCircle,
} from "lucide-react";
import StatCard from "./StatCard";
import EmptyState from "./EmptyState";
import ResultsTable from "./ResultsTable";
import ClaimDetails, { DetailsPlaceholder } from "./ClaimDetails";
import DocumentSummary from "./DocumentSummary";
import { BreakdownBar, CategoryBars, StatusDonut } from "./Charts";
import { ApiError, downloadReport, generateSummary, getReport } from "@/lib/api";
import { saveBlob } from "@/lib/download";
import { STATUS_META } from "@/lib/status";
import {
  applyQuery,
  categoryCounts,
  DEFAULT_QUERY,
  paginate,
  PAGE_SIZE,
  tally,
  type StatusFilter,
  type TableQuery,
} from "@/lib/report";
import type { ClaimStatus, FactCheckReport } from "@/types";

const CARDS: { status: Exclude<StatusFilter, "all" | "PENDING">; key: ClaimStatus; icon: React.ReactNode }[] = [
  { status: "VERIFIED", key: "verified", icon: <CheckCircle2 className="h-4 w-4" /> },
  { status: "INACCURATE", key: "inaccurate", icon: <AlertTriangle className="h-4 w-4" /> },
  { status: "FALSE", key: "false", icon: <XCircle className="h-4 w-4" /> },
  { status: "UNVERIFIED", key: "unverified", icon: <HelpCircle className="h-4 w-4" /> },
];

function Skeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading results">
      <div className="h-8 w-64 animate-pulse rounded-lg bg-slate-100" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-2xl bg-slate-100" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-56 animate-pulse rounded-2xl bg-slate-100" />
        ))}
      </div>
      <div className="h-72 animate-pulse rounded-2xl bg-slate-100" />
    </div>
  );
}

export default function ResultsDashboard({ fileId }: { fileId: string }) {
  const [report, setReport] = useState<FactCheckReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [query, setQueryState] = useState<TableQuery>(DEFAULT_QUERY);
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await getReport(fileId));
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Could not load the results."));
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, [fileId]);

  useEffect(() => {
    void load();
  }, [load]);

  const writeSummary = useCallback(
    async (refresh: boolean) => {
      setGenerating(true);
      try {
        setReport(await generateSummary(fileId, refresh));
      } catch (e) {
        const message = e instanceof Error ? e.message : "The summary could not be generated.";
        setReport((r) => (r ? { ...r, summary: { ...r.summary, narrative_error: message } } : r));
      } finally {
        setGenerating(false);
      }
    },
    [fileId],
  );

  // Write the AI narrative once when a verified report is first opened (the backend caches it).
  const needsNarrative = report?.stage === "verified" && !report.summary.narrative && !report.summary.narrative_error;
  useEffect(() => {
    if (needsNarrative) void writeSummary(false);
  }, [needsNarrative, writeSummary]);

  const onDownload = useCallback(async () => {
    if (downloading) return; // ignore double clicks while a report is being built
    setDownloading(true);
    setDownloadError(null);
    try {
      const { blob, filename } = await downloadReport(fileId);
      saveBlob(blob, filename);
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : "The PDF report could not be downloaded.");
    } finally {
      setDownloading(false);
    }
  }, [downloading, fileId]);

  useEffect(() => {
    if (!selectedId) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setSelectedId(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId]);

  const claims = useMemo(() => report?.claims ?? [], [report]);
  const counts = useMemo(() => tally(claims), [claims]);
  const categories = useMemo(() => categoryCounts(claims), [claims]);
  const matching = useMemo(() => applyQuery(claims, query), [claims, query]);
  const paged = paginate(matching, page, PAGE_SIZE);
  const selected = claims.find((c) => c.claim_id === selectedId) ?? null;

  const setQuery = (q: Partial<TableQuery>) => {
    setQueryState((prev) => ({ ...prev, ...q }));
    setPage(1);
  };
  const clear = () => {
    setQueryState((prev) => ({ ...DEFAULT_QUERY, sortKey: prev.sortKey, sortDir: prev.sortDir }));
    setPage(1);
  };

  if (loading && !report) return <Skeleton />;

  if (error || !report) {
    const gone = error instanceof ApiError && ["file_not_found", "claims_not_extracted"].includes(error.code);
    return (
      <EmptyState
        icon={<AlertCircle className="h-6 w-6 text-red-500" />}
        title={gone ? "This report isn’t available" : "Couldn’t load the results"}
        description={error?.message ?? "Something went wrong."}
        action={
          <div className="flex flex-wrap justify-center gap-2">
            {!gone && (
              <button
                onClick={() => void load()}
                className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-navy-900 hover:bg-slate-50"
              >
                <RefreshCw className="h-4 w-4" /> Try again
              </button>
            )}
            <Link href="/dashboard" className="inline-flex items-center gap-2 rounded-xl bg-navy-900 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-700">
              <Upload className="h-4 w-4" /> Go to upload
            </Link>
          </div>
        }
      />
    );
  }

  const verifiedAny = report.stage === "verified";

  return (
    <div className="space-y-6">
      {/* header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href="/dashboard" className="inline-flex items-center gap-1 text-xs font-semibold text-sky-brand hover:underline">
            <ArrowLeft className="h-3.5 w-3.5" /> Back to upload
          </Link>
          <h1 className="mt-2 text-2xl font-bold text-navy-900 sm:text-3xl">Fact-check results</h1>
          <p className="mt-1 flex items-center gap-1.5 text-slate-500">
            <FileText className="h-4 w-4 shrink-0 text-sky-brand" />
            <span className="truncate" data-testid="document-name">{report.document_name}</span>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-navy-800 hover:bg-slate-50 disabled:opacity-60"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
          <button
            onClick={() => void onDownload()}
            disabled={!report.pdf_ready || downloading}
            aria-busy={downloading}
            title={report.pdf_ready ? "Download the fact-checking report as a PDF" : (report.pdf_blocker ?? "Verification is not complete yet.")}
            className="inline-flex items-center gap-2 rounded-xl bg-navy-900 px-4 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-navy-700 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400 disabled:shadow-none"
          >
            {downloading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            {downloading ? "Generating report…" : "Download PDF Report"}
          </button>
        </div>
      </div>

      {!report.pdf_ready && report.pdf_blocker && (
        <p className="-mt-3 text-xs text-slate-500" role="note">
          PDF report unavailable: {report.pdf_blocker}
        </p>
      )}
      {downloadError && (
        <div className="flex items-start gap-2 rounded-xl bg-red-50 p-3 text-sm text-red-700" role="alert">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="flex-1">
            <p className="font-semibold">The PDF report couldn’t be downloaded</p>
            <p className="mt-0.5">{downloadError}</p>
          </div>
          <button onClick={() => setDownloadError(null)} aria-label="Dismiss error" className="rounded p-0.5 hover:bg-red-100">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {report.warnings.map((w) => (
        <div key={w} className="flex items-start gap-2 rounded-xl bg-orange-50 p-3 text-sm text-orange-800" role="alert">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {w}
        </div>
      ))}

      {!verifiedAny && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm text-navy-800" role="status">
          <p>
            {report.stage === "claims_extracted"
              ? "Claims were extracted, but no evidence has been collected or verified yet."
              : "Evidence was collected, but the claims have not been verified yet."}{" "}
            Finish those steps on the Dashboard page to see verdicts here.
          </p>
          <Link href="/dashboard" className="rounded-xl bg-navy-900 px-4 py-2 text-xs font-semibold text-white hover:bg-navy-700">
            Continue on Dashboard
          </Link>
        </div>
      )}

      {/* status cards */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5" aria-label="Verification summary">
        <StatCard
          label="Total claims analyzed"
          className="col-span-2 lg:col-span-1"
          value={counts.total}
          icon={<ListChecks className="h-4 w-4" />}
          active={query.status === "all"}
          onClick={() => setQuery({ status: "all" })}
        />
        {CARDS.map((c) => (
          <StatCard
            key={c.status}
            label={STATUS_META[c.key].label}
            value={counts[c.key]}
            accent={STATUS_META[c.key].text}
            icon={c.icon}
            active={query.status === c.status}
            onClick={() => setQuery({ status: query.status === c.status ? "all" : c.status })}
          />
        ))}
      </div>
      {counts.pending > 0 && (
        <p className="-mt-3 text-xs text-slate-500">
          {counts.pending} claim{counts.pending === 1 ? " is" : "s are"} not verified yet.{" "}
          <button onClick={() => setQuery({ status: "PENDING" })} className="font-semibold text-sky-brand hover:underline">
            Show them
          </button>
        </p>
      )}

      {/* charts */}
      {counts.total > 0 && (
        <div className="grid gap-4 lg:grid-cols-3">
          <StatusDonut tally={counts} />
          <BreakdownBar tally={counts} />
          <CategoryBars data={categories} />
        </div>
      )}

      <DocumentSummary
        summary={report.summary}
        generating={generating}
        canGenerate={verifiedAny}
        onRegenerate={() => void writeSummary(true)}
        onOpenClaim={(id) => setSelectedId(id)}
      />

      {/* table + details */}
      {counts.total === 0 ? (
        <EmptyState title="No claims were extracted" description="The AI did not find any objectively verifiable claims in this document." />
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
          <ResultsTable
            rows={paged.items}
            totalRows={matching.length}
            page={paged.page}
            pages={paged.pages}
            pageSize={PAGE_SIZE}
            categories={categories}
            query={query}
            onQuery={setQuery}
            onClear={clear}
            onPage={setPage}
            selectedId={selected?.claim_id}
            onSelect={(c) => setSelectedId(c.claim_id)}
          />
          <div
            className={
              selected
                ? "fixed inset-0 z-50 overflow-y-auto bg-slate-900/40 p-4 xl:static xl:z-auto xl:overflow-visible xl:bg-transparent xl:p-0"
                : "hidden xl:block"
            }
          >
            <div className="mx-auto max-w-lg xl:sticky xl:top-24 xl:max-h-[calc(100vh-8rem)] xl:max-w-none xl:overflow-y-auto">
              {selected ? <ClaimDetails claim={selected} onClose={() => setSelectedId(null)} /> : <DetailsPlaceholder />}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
