"use client";

import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Eye, Search, X } from "lucide-react";
import StatusBadge from "./StatusBadge";
import EmptyState from "./EmptyState";
import { STATUS_META } from "@/lib/status";
import {
  badgeStatus,
  categoryLabel,
  isFiltered,
  type SortKey,
  type StatusFilter,
  type TableQuery,
} from "@/lib/report";
import type { ReportClaim } from "@/types";

interface Props {
  rows: ReportClaim[]; // the current page
  totalRows: number; // after filtering, before paging
  page: number;
  pages: number;
  pageSize: number;
  categories: { category: string; count: number }[];
  query: TableQuery;
  onQuery: (q: Partial<TableQuery>) => void;
  onClear: () => void;
  onPage: (p: number) => void;
  selectedId?: string;
  onSelect: (c: ReportClaim) => void;
}

const SORTS: { key: SortKey; label: string }[] = [
  { key: "page", label: "PDF page" },
  { key: "confidence", label: "Confidence" },
  { key: "status", label: "Status (worst first)" },
  { key: "category", label: "Category" },
  { key: "sources", label: "Supporting sources" },
];

function PendingPill() {
  return (
    <span className="inline-flex items-center rounded-full bg-slate-50 px-2.5 py-0.5 text-xs font-semibold text-slate-500 ring-1 ring-inset ring-slate-300/50">
      Not verified yet
    </span>
  );
}

function Verdict({ c }: { c: ReportClaim }) {
  const b = badgeStatus(c.status);
  return b ? <StatusBadge status={b} /> : <PendingPill />;
}

export default function ResultsTable(p: Props) {
  const { query: q } = p;
  const filtered = isFiltered(q);
  const start = p.totalRows === 0 ? 0 : (p.page - 1) * p.pageSize + 1;
  const end = Math.min(p.page * p.pageSize, p.totalRows);

  const sortBy = (key: SortKey) =>
    p.onQuery(q.sortKey === key ? { sortDir: q.sortDir === "asc" ? "desc" : "asc" } : { sortKey: key, sortDir: key === "confidence" || key === "sources" ? "desc" : "asc" });

  const Th = ({ k, children, className = "" }: { k: SortKey; children: React.ReactNode; className?: string }) => (
    <th
      className={`px-4 py-3 font-semibold ${className}`}
      aria-sort={q.sortKey === k ? (q.sortDir === "asc" ? "ascending" : "descending") : "none"}
    >
      <button onClick={() => sortBy(k)} className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-navy-900">
        {children}
        {q.sortKey === k && (q.sortDir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </th>
  );

  return (
    <div className="space-y-3">
      {/* toolbar */}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="relative sm:col-span-3">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="search"
            value={q.search}
            onChange={(e) => p.onQuery({ search: e.target.value })}
            placeholder="Search claims…"
            aria-label="Search claims"
            className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm outline-none focus:border-sky-brand"
          />
        </div>
        <select
          value={q.status}
          onChange={(e) => p.onQuery({ status: e.target.value as StatusFilter })}
          aria-label="Filter by status"
          className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-sky-brand"
        >
          <option value="all">All statuses</option>
          {(["VERIFIED", "INACCURATE", "FALSE", "UNVERIFIED"] as const).map((s) => (
            <option key={s} value={s}>
              {STATUS_META[s.toLowerCase() as keyof typeof STATUS_META].label}
            </option>
          ))}
          <option value="PENDING">Not verified yet</option>
        </select>
        <select
          value={q.category}
          onChange={(e) => p.onQuery({ category: e.target.value })}
          aria-label="Filter by category"
          className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-sky-brand"
        >
          <option value="all">All categories</option>
          {p.categories.map((c) => (
            <option key={c.category} value={c.category}>
              {categoryLabel(c.category)} ({c.count})
            </option>
          ))}
        </select>
        <div className="flex gap-2">
          <select
            value={q.sortKey}
            onChange={(e) => p.onQuery({ sortKey: e.target.value as SortKey })}
            aria-label="Sort by"
            className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-sky-brand"
          >
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>
                Sort: {s.label}
              </option>
            ))}
          </select>
          <button
            onClick={() => p.onQuery({ sortDir: q.sortDir === "asc" ? "desc" : "asc" })}
            aria-label={`Sort direction: ${q.sortDir === "asc" ? "ascending" : "descending"}`}
            className="rounded-xl border border-slate-200 bg-white px-3 text-slate-600 hover:bg-slate-50"
          >
            {q.sortDir === "asc" ? <ArrowUp className="h-4 w-4" /> : <ArrowDown className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {filtered && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500" role="status">
          <span>
            Showing {p.totalRows} matching claim{p.totalRows === 1 ? "" : "s"}
            {q.status !== "all" && <> · status: <strong>{q.status === "PENDING" ? "not verified yet" : q.status.toLowerCase()}</strong></>}
            {q.category !== "all" && <> · category: <strong>{categoryLabel(q.category)}</strong></>}
            {q.search.trim() && <> · “{q.search.trim()}”</>}
          </span>
          <button onClick={p.onClear} className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-navy-800 hover:bg-slate-200">
            <X className="h-3 w-3" /> Clear filters
          </button>
        </div>
      )}

      {p.totalRows === 0 ? (
        <EmptyState
          title="No claims match"
          description={filtered ? "Try a different search term or clear the filters." : "This document has no claims."}
          action={
            filtered ? (
              <button onClick={p.onClear} className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-navy-900 hover:bg-slate-50">
                Clear filters
              </button>
            ) : undefined
          }
        />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-slate-100 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500">
                <tr>
                  <th className="px-4 py-3 font-semibold uppercase tracking-wide">Claim</th>
                  <Th k="category" className="hidden 2xl:table-cell">Category</Th>
                  <Th k="status">Status</Th>
                  <Th k="confidence" className="hidden md:table-cell">Confidence</Th>
                  <Th k="page" className="hidden md:table-cell">Page</Th>
                  <Th k="sources" className="hidden 2xl:table-cell">Supporting</Th>
                  <th className="px-4 py-3 text-right font-semibold uppercase tracking-wide">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {p.rows.map((c) => (
                  <tr
                    key={c.claim_id}
                    data-testid={`row-${c.claim_id}`}
                    onClick={() => p.onSelect(c)}
                    className={`cursor-pointer transition hover:bg-blue-50/50 ${c.claim_id === p.selectedId ? "bg-blue-50" : ""}`}
                  >
                    <td className="min-w-48 max-w-md px-4 py-3 text-navy-900">
                      <p className="line-clamp-3">{c.claim_text}</p>
                      <p className="mt-1 text-xs text-slate-400">
                        <span className="2xl:hidden">
                          {categoryLabel(c.category)} · {c.supporting_count} supporting
                        </span>
                        <span className="md:hidden">
                          {" "}
                          · p.{c.page_number}
                          {c.confidence_score !== null && <> · {c.confidence_score}/100</>}
                        </span>
                      </p>
                    </td>
                    <td className="hidden px-4 py-3 text-slate-600 2xl:table-cell">{categoryLabel(c.category)}</td>
                    <td className="px-4 py-3">
                      <Verdict c={c} />
                    </td>
                    <td className="hidden px-4 py-3 tabular-nums text-slate-600 md:table-cell">
                      {c.confidence_score === null ? <span className="text-slate-300">–</span> : `${c.confidence_score}/100`}
                    </td>
                    <td className="hidden px-4 py-3 tabular-nums text-slate-600 md:table-cell">{c.page_number}</td>
                    <td className="hidden px-4 py-3 tabular-nums text-slate-600 2xl:table-cell">{c.supporting_count}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          p.onSelect(c);
                        }}
                        aria-label={`View details for ${c.claim_id}`}
                        className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-sky-brand hover:bg-blue-50"
                      >
                        <Eye className="h-3.5 w-3.5" /> View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {p.pages > 1 && (
            <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-4 py-3 text-xs text-slate-500">
              <span>
                {start}–{end} of {p.totalRows}
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => p.onPage(p.page - 1)}
                  disabled={p.page <= 1}
                  aria-label="Previous page"
                  className="rounded-lg border border-slate-200 p-1.5 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span>
                  Page {p.page} of {p.pages}
                </span>
                <button
                  onClick={() => p.onPage(p.page + 1)}
                  disabled={p.page >= p.pages}
                  aria-label="Next page"
                  className="rounded-lg border border-slate-200 p-1.5 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
