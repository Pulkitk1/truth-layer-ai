import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, downloadReport } from "@/lib/api";
import { saveBlob } from "@/lib/download";

const pdfResponse = (headers: Record<string, string> = {}) =>
  new Response(new Blob(["%PDF-1.7 fake"]), {
    status: 200,
    headers: { "content-type": "application/pdf", ...headers },
  });

const fetchMock = vi.fn();
beforeEach(() => vi.stubGlobal("fetch", fetchMock));
afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("downloadReport", () => {
  it("requests /api/report/{id} and returns the PDF with the server's filename", async () => {
    fetchMock.mockResolvedValue(
      pdfResponse({ "content-disposition": "attachment; filename=\"truthlayer-fact-check-annual.pdf\"; filename*=UTF-8''x" }),
    );
    const { blob, filename } = await downloadReport("abc123");
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/report\/abc123$/);
    expect(filename).toBe("truthlayer-fact-check-annual.pdf");
    expect(blob.size).toBeGreaterThan(0);
  });

  it("falls back to a default filename and strips path characters from the one it is given", async () => {
    fetchMock.mockResolvedValueOnce(pdfResponse());
    expect((await downloadReport("a")).filename).toBe("truthlayer-fact-check-report.pdf");
    fetchMock.mockResolvedValueOnce(pdfResponse({ "content-disposition": 'attachment; filename="../../evil\\name.pdf"' }));
    expect((await downloadReport("a")).filename).not.toMatch(/[\\/]/);
  });

  it.each([
    [409, { detail: { code: "verification_incomplete", message: "3 of 5 claims are not verified yet." } }, "verification_incomplete", "3 of 5 claims are not verified yet."],
    [404, { detail: { code: "file_not_found", message: "This report was not found or has expired." } }, "file_not_found", "This report was not found or has expired."],
    [500, { detail: { code: "report_generation_failed", message: "The PDF report could not be generated." } }, "report_generation_failed", "The PDF report could not be generated."],
  ])("turns a %i JSON error into a readable ApiError", async (status, body, code, message) => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
    const err = await downloadReport("a").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe(code);
    expect(err.message).toBe(message);
  });

  it("copes with an error that is not JSON", async () => {
    fetchMock.mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 }));
    const err = await downloadReport("a").catch((e) => e);
    expect(err.message).toMatch(/Request failed \(HTTP 502\)/);
  });

  it("explains when the backend is unreachable", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const err = await downloadReport("a").catch((e) => e);
    expect(err.code).toBe("network");
    expect(err.message).toMatch(/Could not reach the TruthLayer backend/);
  });

  it("rejects a successful response that is not a PDF", async () => {
    fetchMock.mockResolvedValue(new Response("<html></html>", { status: 200, headers: { "content-type": "text/html" } }));
    const err = await downloadReport("a").catch((e) => e);
    expect(err.code).toBe("bad_response");
  });
});

describe("saveBlob", () => {
  it("clicks a temporary download link with the filename, then releases the file", () => {
    vi.useFakeTimers();
    const created = vi.fn(() => "blob:fake-url");
    const revoked = vi.fn();
    vi.stubGlobal("URL", { createObjectURL: created, revokeObjectURL: revoked });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe("report.pdf");
      expect(this.getAttribute("href")).toBe("blob:fake-url");
    });
    saveBlob(new Blob(["x"]), "report.pdf");
    expect(click).toHaveBeenCalledTimes(1);
    expect(document.querySelector("a[download]")).toBeNull(); // the temporary link is removed
    expect(revoked).not.toHaveBeenCalled();
    vi.advanceTimersByTime(10_000);
    expect(revoked).toHaveBeenCalledWith("blob:fake-url");
    click.mockRestore();
  });
});
