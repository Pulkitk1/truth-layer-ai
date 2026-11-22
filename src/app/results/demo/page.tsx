"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, HelpCircle, ListChecks, Search, XCircle } from "lucide-react";
import StatCard from "@/components/StatCard";
import ClaimTable from "@/components/ClaimTable";
import ClaimDetailPanel from "@/components/ClaimDetailPanel";
import { DEMO_CLAIMS, DEMO_FILE_NAME } from "@/lib/demoData";
import { STATUS_META, STATUS_ORDER } from "@/lib/status";
import type { Claim, ClaimStatus } from "@/types";

export default function DemoResultsPage() {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<ClaimStatus | "all">("all");
  const [selected, setSelected] = useState<Claim | null>(null);

  const counts = useMemo(() => {
    const c: Record<ClaimStatus, number> = { verified: 0, inaccurate: 0, false: 0, unverified: 0 };
    DEMO_CLAIMS.forEach((cl) => c[cl.status]++);
    return c;
  }, []);

  const filtered = DEMO_CLAIMS.filter(
    (c) =>
      (filter === "all" || c.status === filter) &&
      c.text.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-3 rounded-2xl border border-orange-200 bg-orange-50 p-4 text-sm text-orange-900">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
        <p>
          <strong>DEMO DATA.</strong> Everything on this page is fabricated sample data used to
          preview the UI. These are not real fact-checking results.
        </p>
      </div>

      <div>
        <h1 className="text-2xl font-bold text-navy-900 sm:text-3xl">Results (Demo)</h1>
        <p className="mt-1 text-slate-500">Sample report for “{DEMO_FILE_NAME}” – DEMO DATA</p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatCard
          label="Total claims"
          value={DEMO_CLAIMS.length}
          icon={<ListChecks className="h-4 w-4" />}
          active={filter === "all"}
          onClick={() => setFilter("all")}
        />
        {STATUS_ORDER.map((s) => (
          <StatCard
            key={s}
            label={STATUS_META[s].label}
            value={counts[s]}
            accent={STATUS_META[s].text}
            icon={
              s === "verified" ? <CheckCircle2 className="h-4 w-4" /> :
              s === "unverified" ? <HelpCircle className="h-4 w-4" /> :
              s === "false" ? <XCircle className="h-4 w-4" /> :
              <AlertTriangle className="h-4 w-4" />
            }
            active={filter === s}
            onClick={() => setFilter(filter === s ? "all" : s)}
          />
        ))}
      </div>

      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search claims…"
            className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm outline-none focus:border-sky-brand"
          />
        </div>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value as ClaimStatus | "all")}
          className="rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-sky-brand"
        >
          <option value="all">All statuses</option>
          {STATUS_ORDER.map((s) => (
            <option key={s} value={s}>{STATUS_META[s].label}</option>
          ))}
        </select>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <ClaimTable claims={filtered} selectedId={selected?.id} onSelect={setSelected} />
        <div className="lg:sticky lg:top-24 lg:self-start">
          <ClaimDetailPanel claim={selected} onClose={() => setSelected(null)} />
        </div>
      </div>
    </div>
  );
}
