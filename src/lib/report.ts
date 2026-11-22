import type { ClaimStatus, ReportClaim, ReportStatus } from "@/types";

/** Pure helpers behind the results dashboard (kept free of React so they are easy to test). */

export type StatusFilter = "all" | ReportStatus;
export type SortKey = "page" | "confidence" | "status" | "category" | "sources";
export type SortDir = "asc" | "desc";

export interface TableQuery {
  search: string;
  status: StatusFilter;
  category: string; // "all" or a category id
  sortKey: SortKey;
  sortDir: SortDir;
}

export const DEFAULT_QUERY: TableQuery = {
  search: "",
  status: "all",
  category: "all",
  sortKey: "page",
  sortDir: "asc",
};

export const PAGE_SIZE = 10;

export const STATUS_RANK: Record<ReportStatus, number> = {
  FALSE: 0,
  INACCURATE: 1,
  UNVERIFIED: 2,
  VERIFIED: 3,
  PENDING: 4,
};

export const CATEGORY_LABELS: Record<string, string> = {
  statistics: "Statistics",
  financial: "Financial",
  date_timeline: "Date / Timeline",
  market: "Market",
  scientific: "Scientific",
  technical: "Technical",
  company: "Company",
  demographic: "Demographic",
  other: "Other",
};

export function categoryLabel(c: string) {
  return CATEGORY_LABELS[c] ?? c.replace(/_/g, " ").replace(/^./, (m) => m.toUpperCase());
}

/** Maps backend verdicts (VERIFIED) to the lower-case ids used by StatusBadge and STATUS_META. */
export function badgeStatus(s: ReportStatus): ClaimStatus | null {
  return s === "PENDING" ? null : (s.toLowerCase() as ClaimStatus);
}

export interface Tally {
  total: number;
  verified: number;
  inaccurate: number;
  false: number;
  unverified: number;
  pending: number;
}

/** Counts computed from the claim rows themselves, so cards, charts and table can never disagree. */
export function tally(claims: ReportClaim[]): Tally {
  const t: Tally = { total: claims.length, verified: 0, inaccurate: 0, false: 0, unverified: 0, pending: 0 };
  for (const c of claims) t[c.status.toLowerCase() as keyof Omit<Tally, "total">]++;
  return t;
}

export function categoryCounts(claims: ReportClaim[]) {
  const m = new Map<string, number>();
  for (const c of claims) m.set(c.category, (m.get(c.category) ?? 0) + 1);
  return [...m.entries()]
    .map(([category, count]) => ({ category, count }))
    .sort((a, b) => b.count - a.count || a.category.localeCompare(b.category));
}

export function filterClaims(claims: ReportClaim[], q: TableQuery): ReportClaim[] {
  const needle = q.search.trim().toLowerCase();
  return claims.filter((c) => {
    if (q.status !== "all" && c.status !== q.status) return false;
    if (q.category !== "all" && c.category !== q.category) return false;
    if (!needle) return true;
    const hay = [c.claim_text, c.normalized_claim, c.claim_id, categoryLabel(c.category), c.value ?? "", c.unit ?? "", c.time_period ?? ""]
      .join(" ")
      .toLowerCase();
    return hay.includes(needle);
  });
}

export function sortClaims(claims: ReportClaim[], key: SortKey, dir: SortDir): ReportClaim[] {
  const sign = dir === "asc" ? 1 : -1;
  const val = (c: ReportClaim): number | string => {
    switch (key) {
      case "confidence":
        return c.confidence_score ?? -1;
      case "status":
        return STATUS_RANK[c.status];
      case "category":
        return categoryLabel(c.category);
      case "sources":
        return c.supporting_count;
      default:
        return c.page_number;
    }
  };
  // Stable: ties fall back to page then claim id, so the order is deterministic.
  return [...claims].sort((a, b) => {
    const x = val(a);
    const y = val(b);
    const cmp = typeof x === "string" ? x.localeCompare(y as string) : (x as number) - (y as number);
    return cmp * sign || a.page_number - b.page_number || a.claim_id.localeCompare(b.claim_id);
  });
}

export function paginate<T>(items: T[], page: number, size = PAGE_SIZE) {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const current = Math.min(Math.max(1, page), pages);
  return { items: items.slice((current - 1) * size, current * size), page: current, pages };
}

export function applyQuery(claims: ReportClaim[], q: TableQuery) {
  return sortClaims(filterClaims(claims, q), q.sortKey, q.sortDir);
}

export function isFiltered(q: TableQuery) {
  return q.search.trim() !== "" || q.status !== "all" || q.category !== "all";
}

export function percent(n: number, total: number) {
  return total === 0 ? 0 : Math.round((n / total) * 100);
}
