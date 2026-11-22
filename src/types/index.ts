export type ClaimStatus = "verified" | "inaccurate" | "false" | "unverified";

export interface EvidenceSource {
  title: string;
  url: string;
  snippet: string;
}

export interface Claim {
  id: string;
  text: string;
  page: number;
  status: ClaimStatus;
  confidence: number; // 0-100
  explanation: string;
  correction?: string;
  sources: EvidenceSource[];
}

export interface UploadResult {
  file_id: string;
  filename: string;
  file_size: number;
  upload_status: "uploaded";
}

export interface PageText {
  page_number: number;
  extracted_text: string;
  char_count: number;
  is_empty: boolean;
}

export interface ExtractResult {
  file_id: string;
  filename: string;
  total_pages: number;
  extraction_status: "success" | "partial" | "no_text";
  ocr_required: boolean;
  empty_pages: number[];
  extracted_text: string;
  pages: PageText[];
  message: string | null;
}

export type ClaimCategory =
  | "statistics"
  | "financial"
  | "date_timeline"
  | "market"
  | "scientific"
  | "technical"
  | "company"
  | "demographic"
  | "other";

/** A claim extracted by AI from an uploaded PDF. Always unverified at this stage. */
export interface ExtractedClaim {
  claim_id: string;
  claim_text: string;
  normalized_claim: string;
  category: ClaimCategory;
  value: string | null;
  unit: string | null;
  time_period: string | null;
  context: string | null;
  page_number: number;
  verification_status: "pending";
}

export interface ClaimsResult {
  file_id: string;
  total_claims: number;
  claims: ExtractedClaim[];
  status: "complete" | "partial";
  warnings: string[];
  model: string | null;
}

export type SourceType =
  | "government"
  | "institution"
  | "research"
  | "news"
  | "reference"
  | "web"
  | "community";

/** A web source collected as evidence. The snippet is untrusted and is not proof. */
export interface EvidenceSourceItem {
  title: string;
  url: string;
  content: string;
  published_date: string | null;
  score: number | null;
  domain: string;
  source_type: SourceType;
  claim_id: string;
}

export type SearchStatus = "completed" | "no_results" | "failed" | "skipped";

export interface ClaimSearchResult {
  claim_id: string;
  claim_text: string;
  page_number: number | null;
  search_status: SearchStatus;
  search_query: string | null;
  query_source: "ai" | "rule_based" | null;
  sources: EvidenceSourceItem[];
  sources_found: number;
  cached: boolean;
  error: { code: string; message: string } | null;
  verification_status: "pending";
}

export interface SearchResponse {
  file_id: string;
  total_claims: number;
  total_sources_found: number;
  status: "complete" | "partial";
  search_depth: string;
  claims: ClaimSearchResult[];
  warnings: string[];
}

export type VerdictStatus = "VERIFIED" | "INACCURATE" | "FALSE" | "UNVERIFIED";

export interface VerdictSource {
  title: string;
  url: string;
  relevance: string;
  domain: string;
  source_type: SourceType | string;
  published_date: string | null;
  /** Evidence text as collected from the page (not written by the AI). */
  snippet?: string;
}

export type CorrectionStatus = "confirmed" | "not_confirmed" | "not_applicable";

/** AI fact-check result for one claim (real output, never demo data). */
export interface VerificationResult {
  claim_id: string;
  original_claim: string;
  pdf_page: number | null;
  check_status: "completed" | "failed";
  verification_status: VerdictStatus | null;
  claim_type: "factual" | "prediction" | "hypothetical" | "not_verifiable";
  explanation: string;
  corrected_claim: string | null;
  original_value?: string | null;
  corrected_value?: string | null;
  unit?: string | null;
  reference_period?: string | null;
  correction_explanation?: string | null;
  /** "confirmed" only when the corrected figure appears in a cited source. */
  correction_status?: CorrectionStatus;
  confidence_score: number | null;
  evidence_summary: string;
  supporting_sources: VerdictSource[];
  contradicting_sources: VerdictSource[];
  sources_considered: number;
  adjustments: string[];
  cached: boolean;
  error: { code: string; message: string } | null;
  model: string | null;
}

export interface VerifyResponse {
  file_id: string;
  total_claims: number;
  verified: number;
  inaccurate: number;
  false: number;
  unverified: number;
  failed: number;
  status: "complete" | "partial";
  results: VerificationResult[];
  warnings: string[];
}

export type ReportStatus = VerdictStatus | "PENDING";

/** One row of the results dashboard: a claim with its collected evidence and verdict (all from the backend). */
export interface ReportClaim {
  claim_id: string;
  claim_text: string;
  normalized_claim: string;
  category: string;
  value: string | null;
  unit: string | null;
  time_period: string | null;
  context: string | null;
  page_number: number;
  status: ReportStatus;
  confidence_score: number | null;
  supporting_count: number;
  contradicting_count: number;
  search_status: string | null;
  search_query: string | null;
  collected_sources: EvidenceSourceItem[];
  verification: VerificationResult | null;
  stale: boolean;
}

export interface ReportCounts {
  total: number;
  verified: number;
  inaccurate: number;
  false: number;
  unverified: number;
  pending: number;
}

export interface InvestigationItem {
  claim_id: string;
  claim_text: string;
  status: ReportStatus;
  reason: string;
}

export interface ReportSummary {
  text: string;
  needs_investigation: InvestigationItem[];
  narrative: string | null;
  narrative_error: string | null;
  narrative_model: string | null;
}

export interface FactCheckReport {
  file_id: string;
  document_name: string;
  stage: "claims_extracted" | "evidence_collected" | "verified";
  counts: ReportCounts;
  categories: { category: string; count: number }[];
  claims: ReportClaim[];
  summary: ReportSummary;
  warnings: string[];
  /** The PDF report can be downloaded once every claim has a current verdict. */
  pdf_ready: boolean;
  pdf_blocker: string | null;
}

export interface Report {
  id: string;
  fileName: string;
  createdAt: string;
  totalClaims: number;
}
