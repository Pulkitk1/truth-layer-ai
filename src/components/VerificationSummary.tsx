import { AlertTriangle, CheckCircle2, HelpCircle, ListChecks, XCircle } from "lucide-react";
import StatCard from "./StatCard";
import { STATUS_META } from "@/lib/status";
import type { ClaimStatus } from "@/types";

export type VerdictFilter = "all" | ClaimStatus;

export interface VerdictCounts {
  total: number;
  verified: number;
  inaccurate: number;
  false: number;
  unverified: number;
}

const ICONS: Record<ClaimStatus, React.ReactNode> = {
  verified: <CheckCircle2 className="h-4 w-4" />,
  inaccurate: <AlertTriangle className="h-4 w-4" />,
  false: <XCircle className="h-4 w-4" />,
  unverified: <HelpCircle className="h-4 w-4" />,
};

const ORDER: ClaimStatus[] = ["verified", "inaccurate", "false", "unverified"];

/** Overall verification summary. Each card doubles as a filter for the claim list. */
export default function VerificationSummary({
  counts,
  filter,
  onFilter,
}: {
  counts: VerdictCounts;
  filter: VerdictFilter;
  onFilter: (f: VerdictFilter) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5" aria-label="Verification summary">
      <StatCard
        label="Total claims"
        value={counts.total}
        icon={<ListChecks className="h-4 w-4" />}
        active={filter === "all"}
        onClick={() => onFilter("all")}
      />
      {ORDER.map((s) => (
        <StatCard
          key={s}
          label={STATUS_META[s].label}
          value={counts[s]}
          accent={STATUS_META[s].text}
          icon={ICONS[s]}
          active={filter === s}
          onClick={() => onFilter(filter === s ? "all" : s)}
        />
      ))}
    </div>
  );
}
