import { authHeaders, forgetToken, saveToken } from "@/lib/accessTokens";
import type { ClaimsResult, ExtractResult, FactCheckReport, SearchResponse, UploadResult, VerifyResponse } from "@/types";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

export const MAX_UPLOAD_MB = 20;

export class ApiError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

function parseError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const d = detail as { code?: string; message: string };
    return new ApiError(d.code ?? "error", d.message);
  }
  if (typeof detail === "string") return new ApiError("error", detail);
  return new ApiError("error", `Request failed (HTTP ${status}).`);
}

const NETWORK_MSG =
  "Could not reach the TruthLayer backend. Make sure it is running (see README).";

/** Upload a PDF with progress reporting (fetch has no upload progress, so use XHR). */
export function uploadPdf(
  file: File,
  onProgress: (percent: number) => void,
  signal?: AbortSignal,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/api/upload`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON response */
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        // The token is stored for later requests and deliberately NOT passed on to the UI.
        const { access_token, ...result } = body as UploadResult & { access_token?: string };
        if (access_token) saveToken(result.file_id, access_token);
        resolve(result);
      } else reject(parseError(xhr.status, body));
    };
    xhr.onerror = () => reject(new ApiError("network", NETWORK_MSG));
    xhr.onabort = () => reject(new ApiError("aborted", "Upload cancelled."));
    signal?.addEventListener("abort", () => xhr.abort());

    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export async function extractPdf(fileId: string): Promise<ExtractResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(fileId) },
      body: JSON.stringify({ file_id: fileId }),
    });
  } catch {
    throw new ApiError("network", NETWORK_MSG);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw parseError(res.status, body);
  return body as ExtractResult;
}

export async function extractClaims(fileId: string): Promise<ClaimsResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/claims/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(fileId) },
      body: JSON.stringify({ file_id: fileId }),
    });
  } catch {
    throw new ApiError("network", NETWORK_MSG);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw parseError(res.status, body);
  return body as ClaimsResult;
}

/** Search the web for evidence. Pass claimIds to search only some claims (used for progress). */
export async function searchClaims(
  fileId: string,
  options: { claimIds?: string[]; refresh?: boolean } = {},
): Promise<SearchResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/claims/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(fileId) },
      body: JSON.stringify({
        file_id: fileId,
        claim_ids: options.claimIds,
        refresh: options.refresh ?? false,
      }),
    });
  } catch {
    throw new ApiError("network", NETWORK_MSG);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw parseError(res.status, body);
  return body as SearchResponse;
}

/** AI fact-check claims against the evidence already collected. Pass claimIds for per-claim progress. */
export async function verifyClaims(
  fileId: string,
  options: { claimIds?: string[]; refresh?: boolean } = {},
): Promise<VerifyResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/claims/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(fileId) },
      body: JSON.stringify({
        file_id: fileId,
        claim_ids: options.claimIds,
        refresh: options.refresh ?? false,
      }),
    });
  } catch {
    throw new ApiError("network", NETWORK_MSG);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw parseError(res.status, body);
  return body as VerifyResponse;
}

/** The dashboard data for a document, computed by the backend from its saved results. */
export async function getReport(fileId: string): Promise<FactCheckReport> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/reports/${encodeURIComponent(fileId)}`, {
      headers: authHeaders(fileId),
    });
  } catch {
    throw new ApiError("network", NETWORK_MSG);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw parseError(res.status, body);
  return body as FactCheckReport;
}

/** Asks the backend to add the AI-written narrative to the report summary (cached server-side). */
export async function generateSummary(fileId: string, refresh = false): Promise<FactCheckReport> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/reports/${encodeURIComponent(fileId)}/summary?refresh=${refresh}`, {
      method: "POST",
      headers: authHeaders(fileId),
    });
  } catch {
    throw new ApiError("network", NETWORK_MSG);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw parseError(res.status, body);
  return body as FactCheckReport;
}

/** Downloads the PDF fact-checking report. The backend builds it from saved results (no AI or web calls). */
export async function downloadReport(fileId: string): Promise<{ blob: Blob; filename: string }> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/report/${encodeURIComponent(fileId)}`, {
      headers: authHeaders(fileId),
    });
  } catch {
    throw new ApiError("network", NETWORK_MSG);
  }
  if (!res.ok) {
    // Errors are JSON even though a successful response is a PDF.
    const body = await res.json().catch(() => null);
    throw parseError(res.status, body);
  }
  if (!(res.headers.get("content-type") ?? "").includes("application/pdf")) {
    throw new ApiError("bad_response", "The server did not return a PDF. Please try again.");
  }
  const blob = await res.blob();
  const match = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "");
  const filename = (match?.[1] ?? "truthlayer-fact-check-report.pdf").replace(/[\\/:*?"<>|]+/g, "-");
  return { blob, filename };
}

/** Permanently deletes a document, its stored PDF, reports and results. Also forgets this browser's token for it. */
export async function deleteDocument(fileId: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/files/${encodeURIComponent(fileId)}`, {
      method: "DELETE",
      headers: authHeaders(fileId),
    });
  } catch {
    throw new ApiError("network", NETWORK_MSG);
  }
  if (!res.ok) throw parseError(res.status, await res.json().catch(() => null));
  forgetToken(fileId);
}
