import { describe, expect, it } from "vitest";
import {
  applyQuery,
  categoryCounts,
  DEFAULT_QUERY,
  filterClaims,
  paginate,
  percent,
  sortClaims,
  tally,
} from "@/lib/report";
import { CLAIMS, claim } from "./fixtures";

describe("tally", () => {
  it("counts every status from the claim rows and always adds up to the total", () => {
    const t = tally(CLAIMS);
    expect(t).toEqual({ total: 6, verified: 2, inaccurate: 1, false: 1, unverified: 1, pending: 1 });
    expect(t.verified + t.inaccurate + t.false + t.unverified + t.pending).toBe(t.total);
  });

  it("handles no claims", () => {
    expect(tally([])).toEqual({ total: 0, verified: 0, inaccurate: 0, false: 0, unverified: 0, pending: 0 });
  });
});

describe("categoryCounts", () => {
  it("groups by category, biggest first, and sums to the total", () => {
    const c = categoryCounts(CLAIMS);
    expect(c).toEqual([
      { category: "market", count: 2 },
      { category: "statistics", count: 2 },
      { category: "financial", count: 1 },
      { category: "scientific", count: 1 },
    ]);
    expect(c.reduce((n, x) => n + x.count, 0)).toBe(CLAIMS.length);
  });
});

describe("filterClaims", () => {
  it("filters by status", () => {
    expect(filterClaims(CLAIMS, { ...DEFAULT_QUERY, status: "VERIFIED" }).map((c) => c.claim_id)).toEqual(["claim_001", "claim_002"]);
    expect(filterClaims(CLAIMS, { ...DEFAULT_QUERY, status: "FALSE" })).toHaveLength(1);
    expect(filterClaims(CLAIMS, { ...DEFAULT_QUERY, status: "PENDING" }).map((c) => c.claim_id)).toEqual(["claim_006"]);
  });

  it("filters by category", () => {
    expect(filterClaims(CLAIMS, { ...DEFAULT_QUERY, category: "market" })).toHaveLength(2);
  });

  it("searches claim text, case-insensitively, and by claim id", () => {
    expect(filterClaims(CLAIMS, { ...DEFAULT_QUERY, search: "MOON" }).map((c) => c.claim_id)).toEqual(["claim_004"]);
    expect(filterClaims(CLAIMS, { ...DEFAULT_QUERY, search: "claim_003" })).toHaveLength(1);
    expect(filterClaims(CLAIMS, { ...DEFAULT_QUERY, search: "  billion " }).map((c) => c.claim_id)).toEqual(["claim_002", "claim_005"]);
    expect(filterClaims(CLAIMS, { ...DEFAULT_QUERY, search: "no such text" })).toEqual([]);
  });

  it("combines search, status and category", () => {
    const q = { ...DEFAULT_QUERY, search: "billion", status: "UNVERIFIED" as const, category: "statistics" };
    expect(filterClaims(CLAIMS, q).map((c) => c.claim_id)).toEqual(["claim_005"]);
    expect(filterClaims(CLAIMS, { ...q, category: "market" })).toEqual([]);
  });
});

describe("sortClaims", () => {
  it("sorts by page (default) and reverses", () => {
    expect(sortClaims(CLAIMS, "page", "asc").map((c) => c.page_number)).toEqual([1, 2, 3, 5, 7, 9]);
    expect(sortClaims(CLAIMS, "page", "desc")[0].page_number).toBe(9);
  });

  it("sorts by confidence with unverified-yet claims last in descending order", () => {
    const desc = sortClaims(CLAIMS, "confidence", "desc").map((c) => c.confidence_score);
    expect(desc).toEqual([95, 92, 80, 70, 30, null]);
  });

  it("sorts by status, worst verdict first", () => {
    expect(sortClaims(CLAIMS, "status", "asc").map((c) => c.status)).toEqual(["FALSE", "INACCURATE", "UNVERIFIED", "VERIFIED", "VERIFIED", "PENDING"]);
  });

  it("sorts by category and by supporting sources, and does not mutate the input", () => {
    const before = CLAIMS.map((c) => c.claim_id);
    expect(sortClaims(CLAIMS, "category", "asc")[0].category).toBe("financial");
    expect(sortClaims(CLAIMS, "sources", "desc")[0].claim_id).toBe("claim_001");
    expect(CLAIMS.map((c) => c.claim_id)).toEqual(before);
  });

  it("is deterministic for ties", () => {
    const tied = [claim({ id: 2, text: "b", status: "VERIFIED", page: 1 }), claim({ id: 1, text: "a", status: "VERIFIED", page: 1 })];
    expect(sortClaims(tied, "status", "asc").map((c) => c.claim_id)).toEqual(["claim_001", "claim_002"]);
  });
});

describe("paginate", () => {
  const items = Array.from({ length: 25 }, (_, i) => i + 1);
  it("returns the right slice and page count", () => {
    expect(paginate(items, 1, 10)).toEqual({ items: items.slice(0, 10), page: 1, pages: 3 });
    expect(paginate(items, 3, 10).items).toEqual([21, 22, 23, 24, 25]);
  });
  it("clamps out-of-range pages and handles empty lists", () => {
    expect(paginate(items, 99, 10).page).toBe(3);
    expect(paginate(items, 0, 10).page).toBe(1);
    expect(paginate([], 1, 10)).toEqual({ items: [], page: 1, pages: 1 });
  });
});

describe("misc", () => {
  it("applyQuery filters then sorts", () => {
    const r = applyQuery(CLAIMS, { ...DEFAULT_QUERY, status: "VERIFIED", sortKey: "confidence", sortDir: "desc" });
    expect(r.map((c) => c.claim_id)).toEqual(["claim_001", "claim_002"]);
  });
  it("percent rounds and never divides by zero", () => {
    expect(percent(1, 3)).toBe(33);
    expect(percent(0, 0)).toBe(0);
  });
});
