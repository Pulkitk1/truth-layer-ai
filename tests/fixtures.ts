/**
 * TEST FIXTURES ONLY. These objects imitate backend responses so the dashboard can be tested
 * without a server. They are never shipped or shown in the app.
 */
import { tally } from "@/lib/report";
import type { EvidenceSourceItem, FactCheckReport, ReportClaim, ReportStatus, VerificationResult } from "@/types";

export function source(domain: string, over: Partial<EvidenceSourceItem> = {}): EvidenceSourceItem {
  return {
    title: `Title from ${domain}`,
    url: `https://${domain}/page`,
    content: `Excerpt from ${domain}`,
    published_date: null,
    score: 0.8,
    domain,
    source_type: "news",
    claim_id: "x",
    ...over,
  };
}

interface ClaimOpts {
  id: number;
  text: string;
  status: ReportStatus;
  category?: string;
  page?: number;
  confidence?: number | null;
  supporting?: EvidenceSourceItem[];
  contradicting?: EvidenceSourceItem[];
  other?: EvidenceSourceItem[];
  corrected?: string | null;
  correctedValue?: string | null;
}

export function claim(o: ClaimOpts): ReportClaim {
  const id = `claim_${String(o.id).padStart(3, "0")}`;
  const sup = o.supporting ?? [];
  const con = o.contradicting ?? [];
  const verdict = (s: EvidenceSourceItem) => ({
    title: s.title,
    url: s.url,
    domain: s.domain,
    source_type: s.source_type,
    published_date: s.published_date,
    relevance: `Relevance of ${s.domain}`,
  });
  const verification: VerificationResult | null =
    o.status === "PENDING"
      ? null
      : {
          claim_id: id,
          original_claim: o.text,
          pdf_page: o.page ?? 1,
          check_status: "completed",
          verification_status: o.status,
          claim_type: "factual",
          explanation: `Explanation for ${id}`,
          corrected_claim: o.corrected ?? null,
          original_value: o.correctedValue ? "10 million" : null,
          corrected_value: o.correctedValue ?? null,
          unit: o.correctedValue ? "units" : null,
          reference_period: o.correctedValue ? "2023" : null,
          correction_explanation: o.correctedValue ? "The source reports 14 million units." : null,
          correction_status: o.correctedValue ? "confirmed" : o.status === "INACCURATE" || o.status === "FALSE" ? "not_confirmed" : "not_applicable",
          confidence_score: o.confidence ?? 80,
          evidence_summary: `Summary for ${id}`,
          supporting_sources: sup.map(verdict),
          contradicting_sources: con.map(verdict),
          sources_considered: sup.length + con.length,
          adjustments: [],
          cached: false,
          error: null,
          model: "m",
        };
  return {
    claim_id: id,
    claim_text: o.text,
    normalized_claim: o.text,
    category: o.category ?? "statistics",
    value: null,
    unit: null,
    time_period: null,
    context: null,
    page_number: o.page ?? 1,
    status: o.status,
    confidence_score: o.status === "PENDING" ? null : (o.confidence ?? 80),
    supporting_count: sup.length,
    contradicting_count: con.length,
    search_status: "completed",
    search_query: `query ${id}`,
    collected_sources: [...sup, ...con, ...(o.other ?? [])].map((s) => ({ ...s, claim_id: id })),
    verification,
    stale: false,
  };
}

export const CLAIMS: ReportClaim[] = [
  claim({ id: 1, text: "Alpha revenue grew 10 percent in 2023.", status: "VERIFIED", category: "financial", page: 1, confidence: 92, supporting: [source("reuters.com", { published_date: "2024-02-01" }), source("sec.gov", { source_type: "government" })] }),
  claim({ id: 2, text: "Beta market reached 50 billion dollars.", status: "VERIFIED", category: "market", page: 2, confidence: 70, supporting: [source("bbc.com")] }),
  claim({ id: 3, text: "Gamma sold 10 million units in 2022.", status: "INACCURATE", category: "market", page: 3, confidence: 80, contradicting: [source("iea.org", { source_type: "institution" })], corrected: "Gamma sold 14 million units in 2023.", correctedValue: "14 million" }),
  claim({ id: 4, text: "Delta is visible from the Moon.", status: "FALSE", category: "scientific", page: 5, confidence: 95, contradicting: [source("nasa.gov", { source_type: "government" }), source("snopes.com")] }),
  claim({ id: 5, text: "Epsilon will have 1 billion users by 2030.", status: "UNVERIFIED", category: "statistics", page: 7, confidence: 30, other: [source("random.com", { source_type: "web" })] }),
  claim({ id: 6, text: "Zeta sales rose sharply last year.", status: "PENDING", category: "statistics", page: 9 }),
];

export function makeReport(claims: ReportClaim[] = CLAIMS, over: Partial<FactCheckReport> = {}): FactCheckReport {
  const t = tally(claims);
  const cats = new Map<string, number>();
  claims.forEach((c) => cats.set(c.category, (cats.get(c.category) ?? 0) + 1));
  return {
    file_id: "f".repeat(32),
    document_name: "annual-report.pdf",
    stage: "verified",
    counts: t,
    categories: [...cats.entries()].map(([category, count]) => ({ category, count })),
    claims,
    summary: {
      text: `${t.total} claims analysed: ${t.verified} verified.`,
      needs_investigation: [
        { claim_id: "claim_005", claim_text: claims.find((c) => c.claim_id === "claim_005")?.claim_text ?? "", status: "UNVERIFIED", reason: "A forecast, so it cannot be confirmed as a fact." },
      ],
      narrative: "Narrative about the results.",
      narrative_error: null,
      narrative_model: "test-model",
    },
    warnings: [],
    pdf_ready: t.pending === 0,
    pdf_blocker: t.pending === 0 ? null : `${t.pending} of ${t.total} claims are not verified yet. Search the web for evidence and verify all claims first.`,
    ...over,
  };
}
