"use client";

import { useState } from "react";
import { categoryLabel, percent, type Tally } from "@/lib/report";

/** Status colours follow the app-wide convention: green verified, orange inaccurate, red false, grey unverified. */
const SEGMENTS = [
  { key: "verified", label: "Verified", color: "#22c55e" },
  { key: "inaccurate", label: "Inaccurate", color: "#f97316" },
  { key: "false", label: "False", color: "#ef4444" },
  { key: "unverified", label: "Unverified", color: "#94a3b8" },
  { key: "pending", label: "Not verified yet", color: "#e2e8f0" },
] as const;

function segments(t: Tally) {
  return SEGMENTS.map((s) => ({ ...s, value: t[s.key] })).filter((s) => s.value > 0);
}

function Legend({ t, active, onHover }: { t: Tally; active: string | null; onHover: (k: string | null) => void }) {
  return (
    <ul className="space-y-1.5 text-sm">
      {SEGMENTS.filter((s) => s.key !== "pending" || t.pending > 0).map((s) => (
        <li
          key={s.key}
          onMouseEnter={() => onHover(s.key)}
          onMouseLeave={() => onHover(null)}
          className={`flex items-center justify-between gap-4 rounded-lg px-2 py-1 ${active === s.key ? "bg-slate-50" : ""}`}
        >
          <span className="flex items-center gap-2 text-slate-600">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
            {s.label}
          </span>
          <span className="tabular-nums text-navy-900">
            <strong>{t[s.key]}</strong> <span className="text-slate-400">({percent(t[s.key], t.total)}%)</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function ChartCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm">
      <h3 className="text-sm font-semibold text-navy-900">{title}</h3>
      {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** Donut of verdict counts. The legend beside it doubles as the data table. */
export function StatusDonut({ tally }: { tally: Tally }) {
  const [hover, setHover] = useState<string | null>(null);
  const segs = segments(tally);
  const R = 52;
  const C = 2 * Math.PI * R;
  const GAP = segs.length > 1 ? 2 : 0; // 2px surface gap between segments
  let offset = 0;

  return (
    <ChartCard title="Verification status distribution" subtitle="Share of claims by verdict">
      <div className="flex flex-wrap items-center gap-6">
        <svg
          viewBox="0 0 140 140"
          className="h-36 w-36 shrink-0"
          role="img"
          aria-label={`Status distribution: ${SEGMENTS.map((s) => `${tally[s.key]} ${s.label}`).join(", ")}`}
        >
          <circle cx="70" cy="70" r={R} fill="none" stroke="#f1f5f9" strokeWidth="16" />
          {tally.total > 0 &&
            segs.map((s) => {
              const len = (s.value / tally.total) * C;
              const dash = Math.max(len - GAP, 0.5);
              const el = (
                <circle
                  key={s.key}
                  cx="70"
                  cy="70"
                  r={R}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={hover === s.key ? 20 : 16}
                  strokeDasharray={`${dash} ${C - dash}`}
                  strokeDashoffset={-offset}
                  transform="rotate(-90 70 70)"
                  onMouseEnter={() => setHover(s.key)}
                  onMouseLeave={() => setHover(null)}
                >
                  <title>{`${s.label}: ${s.value} (${percent(s.value, tally.total)}%)`}</title>
                </circle>
              );
              offset += len;
              return el;
            })}
          <text x="70" y="68" textAnchor="middle" className="fill-navy-900 text-[22px] font-bold">
            {tally.total}
          </text>
          <text x="70" y="84" textAnchor="middle" className="fill-slate-400 text-[9px]">
            claims
          </text>
        </svg>
        <div className="min-w-48 flex-1">
          <Legend t={tally} active={hover} onHover={setHover} />
        </div>
      </div>
    </ChartCard>
  );
}

/** One stacked bar for the whole document, segments separated by a 2px gap. */
export function BreakdownBar({ tally }: { tally: Tally }) {
  const [hover, setHover] = useState<string | null>(null);
  const segs = segments(tally);
  return (
    <ChartCard title="Overall verification breakdown" subtitle="How the document's claims were resolved">
      {tally.total === 0 ? (
        <p className="text-sm text-slate-500">No claims to show.</p>
      ) : (
        <>
          <div
            className="flex h-4 w-full gap-0.5 overflow-hidden rounded-full"
            role="img"
            aria-label={`Breakdown: ${segs.map((s) => `${s.value} ${s.label}`).join(", ")}`}
          >
            {segs.map((s) => (
              <div
                key={s.key}
                title={`${s.label}: ${s.value} (${percent(s.value, tally.total)}%)`}
                onMouseEnter={() => setHover(s.key)}
                onMouseLeave={() => setHover(null)}
                className="h-full transition-opacity"
                style={{ width: `${(s.value / tally.total) * 100}%`, background: s.color, opacity: hover && hover !== s.key ? 0.45 : 1 }}
              />
            ))}
          </div>
          <div className="mt-4">
            <Legend t={tally} active={hover} onHover={setHover} />
          </div>
        </>
      )}
    </ChartCard>
  );
}

/** Horizontal bars, one per category, with the count written at the end of each bar. */
export function CategoryBars({ data }: { data: { category: string; count: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  const total = data.reduce((n, d) => n + d.count, 0);
  return (
    <ChartCard title="Claims by category" subtitle="What kinds of claims the document makes">
      {data.length === 0 ? (
        <p className="text-sm text-slate-500">No claims to show.</p>
      ) : (
        <ul className="space-y-2.5" aria-label="Claims by category">
          {data.map((d) => (
            <li key={d.category} className="grid grid-cols-[7.5rem_1fr_2rem] items-center gap-3 text-sm" title={`${categoryLabel(d.category)}: ${d.count} (${percent(d.count, total)}%)`}>
              <span className="truncate text-slate-600">{categoryLabel(d.category)}</span>
              <span className="h-3 rounded-r-md bg-slate-100">
                <span className="block h-full rounded-r-md bg-navy-700" style={{ width: `${(d.count / max) * 100}%` }} />
              </span>
              <span className="text-right font-semibold tabular-nums text-navy-900">{d.count}</span>
            </li>
          ))}
        </ul>
      )}
    </ChartCard>
  );
}
