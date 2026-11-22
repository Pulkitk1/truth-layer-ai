import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { authHeaders, forgetToken, getToken, saveToken } from "@/lib/accessTokens";
import {
  ApiError,
  deleteDocument,
  downloadReport,
  extractClaims,
  extractPdf,
  generateSummary,
  getReport,
  searchClaims,
  uploadPdf,
  verifyClaims,
} from "@/lib/api";

const TOKEN = "T".repeat(43);
const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  window.localStorage.clear();
  forgetToken("doc1");
  forgetToken("doc2");
});
afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("access token storage", () => {
  it("saves, reads and forgets a token per document", () => {
    saveToken("doc1", TOKEN);
    saveToken("doc2", "U".repeat(43));
    expect(getToken("doc1")).toBe(TOKEN);
    expect(authHeaders("doc2")).toEqual({ Authorization: `Bearer ${"U".repeat(43)}` });
    forgetToken("doc1");
    expect(getToken("doc1")).toBeNull();
    expect(authHeaders("doc1")).toEqual({});
  });

  it("keeps working in memory when localStorage is blocked", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    saveToken("doc1", TOKEN);
    expect(getToken("doc1")).toBe(TOKEN);
    spy.mockRestore();
  });

  it("keeps only the most recent documents", () => {
    for (let i = 0; i < 25; i++) saveToken(`id${i}`, `tok${i}`.padEnd(30, "x"));
    const stored = JSON.parse(window.localStorage.getItem("truthlayer:access-tokens") ?? "{}");
    expect(Object.keys(stored)).toHaveLength(20);
    expect(stored.id0).toBeUndefined();
    expect(stored.id24).toBeDefined();
  });

  it("survives corrupt storage", () => {
    window.localStorage.setItem("truthlayer:access-tokens", "{not json");
    expect(getToken("never-saved")).toBeNull();
  });
});

describe("requests carry the document's token in the Authorization header only", () => {
  beforeEach(() => saveToken("doc1", TOKEN));

  const sent = () => {
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    return { url: String(url), headers: (init?.headers ?? {}) as Record<string, string> };
  };

  it.each([
    ["extractPdf", () => extractPdf("doc1")],
    ["extractClaims", () => extractClaims("doc1")],
    ["searchClaims", () => searchClaims("doc1")],
    ["verifyClaims", () => verifyClaims("doc1")],
    ["getReport", () => getReport("doc1")],
    ["generateSummary", () => generateSummary("doc1")],
  ])("%s", async (_name, run) => {
    fetchMock.mockResolvedValue(json({}));
    await run();
    const { url, headers } = sent();
    expect(headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(url).not.toContain(TOKEN); // never in the URL
  });

  it("downloadReport", async () => {
    fetchMock.mockResolvedValue(new Response(new Blob(["%PDF-"]), { status: 200, headers: { "content-type": "application/pdf" } }));
    await downloadReport("doc1");
    expect(sent().headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(sent().url).not.toContain(TOKEN);
  });

  it("sends no Authorization header for a document this browser has no token for", async () => {
    fetchMock.mockResolvedValue(json({}));
    await getReport("someone-elses-doc");
    expect(sent().headers.Authorization).toBeUndefined();
  });

  it("shows the server's message when access is refused", async () => {
    fetchMock.mockResolvedValue(json({ detail: { code: "invalid_token", message: "You do not have access to this document." } }, 403));
    await expect(getReport("doc1")).rejects.toMatchObject({ code: "invalid_token", message: "You do not have access to this document." });
    fetchMock.mockResolvedValue(json({ detail: { code: "missing_token", message: "This document needs its access token." } }, 401));
    await expect(getReport("doc2")).rejects.toBeInstanceOf(ApiError);
  });

  it("deleteDocument sends the token and then forgets it", async () => {
    fetchMock.mockResolvedValue(json({ status: "deleted" }));
    await deleteDocument("doc1");
    expect(sent().headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(getToken("doc1")).toBeNull();
  });

  it("deleteDocument keeps the token if the delete failed, so it can be retried", async () => {
    fetchMock.mockResolvedValue(json({ detail: { code: "storage_unavailable", message: "File storage is temporarily unavailable." } }, 503));
    await expect(deleteDocument("doc1")).rejects.toMatchObject({ code: "storage_unavailable" });
    expect(getToken("doc1")).toBe(TOKEN);
  });
});

describe("uploadPdf", () => {
  class FakeXhr {
    static last: FakeXhr;
    status = 200;
    responseText = "";
    upload: { onprogress?: (e: unknown) => void } = {};
    onload?: () => void;
    onerror?: () => void;
    onabort?: () => void;
    open = vi.fn();
    send = vi.fn(() => {
      this.responseText = JSON.stringify({
        file_id: "doc9",
        filename: "a.pdf",
        file_size: 5,
        upload_status: "uploaded",
        access_token: "N".repeat(43),
      });
      this.onload?.();
    });
    abort = vi.fn();
    constructor() {
      FakeXhr.last = this;
    }
  }

  it("stores the token it receives and does not hand it to the UI", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const result = await uploadPdf(new File(["%PDF-"], "a.pdf"), () => {});
    expect(result).toEqual({ file_id: "doc9", filename: "a.pdf", file_size: 5, upload_status: "uploaded" });
    expect(JSON.stringify(result)).not.toContain("N".repeat(43));
    expect(getToken("doc9")).toBe("N".repeat(43));
    forgetToken("doc9");
  });
});
