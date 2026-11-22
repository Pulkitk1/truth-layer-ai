import type { Claim } from "@/types";
import StatusBadge from "./StatusBadge";
import EmptyState from "./EmptyState";

interface ClaimTableProps {
  claims: Claim[];
  selectedId?: string;
  onSelect: (claim: Claim) => void;
}

export default function ClaimTable({ claims, selectedId, onSelect }: ClaimTableProps) {
  if (claims.length === 0) {
    return (
      <EmptyState
        title="No claims match"
        description="Try a different search term or clear the status filter."
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-100 bg-white shadow-sm">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3 font-semibold">Claim</th>
              <th className="px-4 py-3 font-semibold">Page</th>
              <th className="px-4 py-3 font-semibold">Status</th>
              <th className="hidden px-4 py-3 font-semibold sm:table-cell">Confidence</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {claims.map((c) => (
              <tr
                key={c.id}
                onClick={() => onSelect(c)}
                className={`cursor-pointer transition hover:bg-blue-50/50 ${
                  c.id === selectedId ? "bg-blue-50" : ""
                }`}
              >
                <td className="max-w-md px-4 py-3 text-navy-900">{c.text}</td>
                <td className="px-4 py-3 text-slate-500">{c.page}</td>
                <td className="px-4 py-3">
                  <StatusBadge status={c.status} />
                </td>
                <td className="hidden px-4 py-3 text-slate-500 sm:table-cell">
                  {c.confidence}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
