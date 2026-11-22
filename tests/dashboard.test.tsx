import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { CLAIMS, claim, makeReport, source } from "./fixtures";

const getReport = vi.fn();
const generateSummary = vi.fn();
const downloadReport = vi.fn();
const saveBlob = vi.fn();

vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    getReport: (...a: unknown[]) => getReport(...a),
    generateSummary: (...a: unknown[]) => generateSummary(...a),
    downloadReport: (...a: unknown[]) => downloadReport(...a),
  };
});
vi.mock("@/lib/download", () => ({ saveBlob: (...a: unknown[]) => saveBlob(...a) }));

import ResultsDashboard from "@/components/ResultsDashboard";

async function open(report = makeReport()) {
  getReport.mockResolvedValue(report);
  generateSummary.mockResolvedValue(report);
  render(<ResultsDashboard fileId={report.file_id} />);
  await screen.findByTestId("document-name");
}

const cards = () => screen.getByLabelText("Verification summary");
/** The whole card (a button) that contains the given label. */
const card = (label: string) => within(cards()).getByText(label).closest("button") as HTMLElement;
const rowIds = () => screen.queryAllByTestId(/^row-/).map((r) => r.getAttribute("data-testid"));

beforeEach(() => {
  getReport.mockReset();
  generateSummary.mockReset();
  downloadReport.mockReset();
  saveBlob.mockReset();
});

describe("overview statistics", () => {
  it("shows the document name and counts from the backend report", async () => {
    await open();
    expect(screen.getByTestId("document-name")).toHaveTextContent("annual-report.pdf");
    expect(card("Total claims analyzed")).toHaveTextContent(/^Total claims analyzed6$/);
    expect(card("Verified")).toHaveTextContent(/^Verified2$/);
    expect(card("Inaccurate")).toHaveTextContent(/^Inaccurate1$/);
    expect(card("False")).toHaveTextContent(/^False1$/);
    expect(card("Unverified")).toHaveTextContent(/^Unverified1$/);
  });

  it("computes statistics from the claims returned, not from fixed numbers", async () => {
    const claims = [claim({ id: 1, text: "Only claim.", status: "FALSE", contradicting: [source("nasa.gov")] }), claim({ id: 2, text: "Another.", status: "FALSE" })];
    await open(makeReport(claims));
    expect(card("False")).toHaveTextContent(/^False2$/);
    expect(card("Verified")).toHaveTextContent(/^Verified0$/);
    expect(card("Total claims analyzed")).toHaveTextContent(/^Total claims analyzed2$/);
    expect(rowIds()).toHaveLength(2);
  });

  it("flags claims that are not verified yet and can show them", async () => {
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Show them" }));
    expect(rowIds()).toEqual(["row-claim_006"]);
  });

  it("draws the charts from the same counts", async () => {
    await open();
    expect(screen.getByRole("img", { name: /Status distribution: 2 Verified, 1 Inaccurate, 1 False, 1 Unverified, 1 Not verified yet/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Breakdown: 2 Verified/ })).toBeInTheDocument();
    const cats = within(screen.getByLabelText("Claims by category", { selector: "ul" }));
    expect(cats.getByText("Market").closest("li")).toHaveTextContent("2");
    expect(cats.getByText("Financial").closest("li")).toHaveTextContent("1");
  });
});

describe("status cards and filters", () => {
  it("lists all claims by default", async () => {
    await open();
    expect(rowIds()).toHaveLength(6);
  });

  it("clicking a status card filters the table, and clicking again clears it", async () => {
    await open();
    await userEvent.click(within(cards()).getByText("Verified"));
    expect(rowIds()).toEqual(["row-claim_001", "row-claim_002"]);
    expect(screen.getByLabelText("Filter by status")).toHaveValue("VERIFIED");
    await userEvent.click(within(cards()).getByText("Verified"));
    expect(rowIds()).toHaveLength(6);
  });

  it.each([
    ["Inaccurate", ["row-claim_003"]],
    ["False", ["row-claim_004"]],
    ["Unverified", ["row-claim_005"]],
  ])("the %s card shows only those claims", async (label, expected) => {
    await open();
    await userEvent.click(within(cards()).getByText(label));
    expect(rowIds()).toEqual(expected);
  });

  it("the Clear filters button resets everything", async () => {
    await open();
    await userEvent.click(within(cards()).getByText("False"));
    await userEvent.type(screen.getByLabelText("Search claims"), "moon");
    expect(rowIds()).toEqual(["row-claim_004"]);
    await userEvent.click(screen.getByRole("button", { name: /Clear filters/ }));
    expect(rowIds()).toHaveLength(6);
    expect(screen.getByLabelText("Search claims")).toHaveValue("");
    expect(screen.getByLabelText("Filter by status")).toHaveValue("all");
  });

  it("filters by category using the dropdown", async () => {
    await open();
    await userEvent.selectOptions(screen.getByLabelText("Filter by category"), "market");
    expect(rowIds()).toEqual(["row-claim_002", "row-claim_003"]);
  });
});

describe("search and sorting", () => {
  it("searches claim text", async () => {
    await open();
    await userEvent.type(screen.getByLabelText("Search claims"), "billion");
    expect(rowIds()).toEqual(["row-claim_002", "row-claim_005"]);
  });

  it("shows an empty state when nothing matches", async () => {
    await open();
    await userEvent.type(screen.getByLabelText("Search claims"), "zzzzz");
    expect(rowIds()).toHaveLength(0);
    expect(screen.getByText("No claims match")).toBeInTheDocument();
  });

  it("sorts by confidence when asked", async () => {
    await open();
    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "confidence");
    // direction toggles to descending by clicking the column header for a fresh sort
    await userEvent.click(screen.getByRole("button", { name: /^Sort direction/ }));
    expect(rowIds()[0]).toBe("row-claim_004"); // highest confidence (95)
  });

  it("paginates long lists", async () => {
    const many = Array.from({ length: 23 }, (_, i) => claim({ id: i + 1, text: `Claim number ${i + 1}`, status: "VERIFIED", page: i + 1, supporting: [source("reuters.com")] }));
    await open(makeReport(many));
    expect(rowIds()).toHaveLength(10);
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(rowIds()[0]).toBe("row-claim_011");
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(rowIds()).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });
});

describe("claim details", () => {
  it("shows the verdict, explanation, correction, confidence and page", async () => {
    await open();
    await userEvent.click(screen.getByTestId("row-claim_003"));
    const d = within(screen.getByLabelText("Claim details"));
    expect(d.getByText(/Gamma sold 10 million units in 2022/)).toBeInTheDocument();
    expect(d.getByText("Explanation for claim_003")).toBeInTheDocument();
    expect(d.getByText("Gamma sold 14 million units in 2023.")).toBeInTheDocument();
    expect(d.getByText("80/100")).toBeInTheDocument();
    expect(d.getByText(/PDF page 3/)).toBeInTheDocument();
    expect(d.getByText("Inaccurate")).toBeInTheDocument();
  });

  it("separates supporting from contradicting evidence with working links and dates", async () => {
    await open(makeReport([claim({ id: 1, text: "Mixed.", status: "UNVERIFIED", supporting: [source("reuters.com", { published_date: "2024-02-01" })], contradicting: [source("sec.gov", { source_type: "government" })] })]));
    await userEvent.click(screen.getByTestId("row-claim_001"));
    const sup = within(screen.getByRole("region", { name: "Supporting evidence" }));
    const con = within(screen.getByRole("region", { name: "Contradicting evidence" }));
    const supLink = sup.getByRole("link", { name: /Title from reuters.com/ });
    expect(supLink).toHaveAttribute("href", "https://reuters.com/page");
    expect(supLink).toHaveAttribute("target", "_blank");
    expect(supLink).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(sup.getByText("2024-02-01")).toBeInTheDocument();
    expect(con.getByRole("link", { name: /Title from sec.gov/ })).toHaveAttribute("href", "https://sec.gov/page");
    expect(sup.queryByText(/sec.gov/)).toBeNull();
    expect(con.queryByText(/reuters.com/)).toBeNull();
  });

  it("does not make links out of unsafe URLs", async () => {
    const bad = source("evil.example", { url: "javascript:alert(1)" });
    await open(makeReport([claim({ id: 1, text: "X.", status: "VERIFIED", supporting: [bad] })]));
    await userEvent.click(screen.getByTestId("row-claim_001"));
    expect(screen.queryByRole("link", { name: /Title from evil.example/ })).toBeNull();
    expect(screen.getByText(/Title from evil.example/)).toBeInTheDocument();
  });

  it("tells the user when a claim has no verdict yet", async () => {
    await open();
    await userEvent.click(screen.getByTestId("row-claim_006"));
    expect(within(screen.getByLabelText("Claim details")).getByText(/has not been fact-checked yet/)).toBeInTheDocument();
  });

  it("lists collected sources that the verdict did not cite", async () => {
    await open();
    await userEvent.click(screen.getByTestId("row-claim_005"));
    expect(within(screen.getByLabelText("Claim details")).getByText(/Other collected sources \(1\)/)).toBeInTheDocument();
  });

  it("closes with the close button and with Escape", async () => {
    await open();
    await userEvent.click(screen.getByTestId("row-claim_001"));
    await userEvent.click(screen.getByRole("button", { name: "Close details" }));
    expect(screen.queryByLabelText("Claim details")).toBeNull();
    await userEvent.click(screen.getByTestId("row-claim_001"));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByLabelText("Claim details")).toBeNull();
  });

  it("opens a claim from the follow-up list", async () => {
    await open();
    await userEvent.click(within(screen.getByLabelText("Document summary")).getByRole("button", { name: /Epsilon will have/ }));
    expect(within(screen.getByLabelText("Claim details")).getByText("Explanation for claim_005")).toBeInTheDocument();
  });
});

describe("document summary", () => {
  it("shows the built-in summary, the AI narrative and the follow-up list", async () => {
    await open();
    const s = within(screen.getByLabelText("Document summary"));
    expect(s.getByText("6 claims analysed: 2 verified.")).toBeInTheDocument();
    expect(s.getByText("Narrative about the results.")).toBeInTheDocument();
    expect(s.getByText(/Needs further investigation \(1\)/)).toBeInTheDocument();
    expect(generateSummary).not.toHaveBeenCalled(); // already available, so nothing is regenerated
  });

  it("asks the backend for the narrative when it is missing, and shows it", async () => {
    const without = makeReport(CLAIMS, { summary: { ...makeReport().summary, narrative: null, narrative_model: null } });
    getReport.mockResolvedValue(without);
    generateSummary.mockResolvedValue(makeReport());
    render(<ResultsDashboard fileId={"f".repeat(32)} />);
    expect(await screen.findByText("Narrative about the results.")).toBeInTheDocument();
    expect(generateSummary).toHaveBeenCalledTimes(1);
  });

  it("keeps the built-in summary when the AI summary fails", async () => {
    const without = makeReport(CLAIMS, { summary: { ...makeReport().summary, narrative: null } });
    getReport.mockResolvedValue(without);
    generateSummary.mockRejectedValue(new ApiError("groq_timeout", "The Groq request timed out."));
    render(<ResultsDashboard fileId={"f".repeat(32)} />);
    expect(await screen.findByText(/AI summary unavailable: The Groq request timed out./)).toBeInTheDocument();
    expect(screen.getByText("6 claims analysed: 2 verified.")).toBeInTheDocument();
  });
});

describe("loading, empty and error states", () => {
  it("shows a loading state first", async () => {
    getReport.mockReturnValue(new Promise(() => {}));
    render(<ResultsDashboard fileId={"a".repeat(32)} />);
    expect(screen.getByRole("status", { name: "Loading results" })).toBeInTheDocument();
  });

  it("shows an error with a retry when the API fails, then recovers", async () => {
    getReport.mockRejectedValueOnce(new ApiError("network", "Could not reach the TruthLayer backend."));
    render(<ResultsDashboard fileId={"a".repeat(32)} />);
    expect(await screen.findByText("Couldn’t load the results")).toBeInTheDocument();
    expect(screen.getByText("Could not reach the TruthLayer backend.")).toBeInTheDocument();
    getReport.mockResolvedValue(makeReport());
    await userEvent.click(screen.getByRole("button", { name: /Try again/ }));
    expect(await screen.findByTestId("document-name")).toBeInTheDocument();
  });

  it("explains an expired report without offering a pointless retry", async () => {
    getReport.mockRejectedValue(new ApiError("file_not_found", "This report was not found or has expired."));
    render(<ResultsDashboard fileId={"a".repeat(32)} />);
    expect(await screen.findByText("This report isn’t available")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Go to upload/ })).toHaveAttribute("href", "/dashboard");
  });

  it("shows an empty state for a document with no claims", async () => {
    await open(makeReport([], { summary: { ...makeReport().summary, narrative: null, needs_investigation: [], text: "No factual claims were extracted from this document." } }));
    expect(screen.getByText("No claims were extracted")).toBeInTheDocument();
    expect(screen.queryByLabelText("Search claims")).toBeNull();
  });

  it("guides the user when claims are not verified yet", async () => {
    const pending = CLAIMS.map((c) => claim({ id: Number(c.claim_id.slice(-3)), text: c.claim_text, status: "PENDING", category: c.category }));
    await open(makeReport(pending, { stage: "evidence_collected" }));
    expect(screen.getByText(/have not been verified yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue on Dashboard" })).toBeInTheDocument();
    expect(generateSummary).not.toHaveBeenCalled();
  });

  it("shows backend warnings", async () => {
    await open(makeReport(CLAIMS, { warnings: ["1 claim(s) have new evidence since they were verified."] }));
    await waitFor(() => expect(screen.getByText(/have new evidence/)).toBeInTheDocument());
  });
});

describe("PDF report download", () => {
  const complete = () => makeReport(CLAIMS.filter((c) => c.status !== "PENDING"));
  const button = () => screen.getByRole("button", { name: /Download PDF Report|Generating report/ });

  it("is enabled once every claim has a verdict", async () => {
    await open(complete());
    expect(button()).toBeEnabled();
    expect(screen.queryByText(/PDF report unavailable/)).toBeNull();
  });

  it("is disabled while verification is pending, and says why", async () => {
    await open(makeReport()); // one claim is still not verified
    expect(button()).toBeDisabled();
    expect(button()).toHaveAttribute("title", expect.stringContaining("1 of 6 claims are not verified yet"));
    expect(screen.getByText(/PDF report unavailable: 1 of 6 claims are not verified yet/)).toBeInTheDocument();
    await userEvent.click(button());
    expect(downloadReport).not.toHaveBeenCalled();
  });

  it("fetches the PDF for this document and hands it to the browser", async () => {
    const blob = new Blob(["%PDF-1.7"], { type: "application/pdf" });
    downloadReport.mockResolvedValue({ blob, filename: "truthlayer-fact-check-annual-report.pdf" });
    const report = complete();
    await open(report);
    await userEvent.click(button());
    await waitFor(() => expect(saveBlob).toHaveBeenCalledTimes(1));
    expect(downloadReport).toHaveBeenCalledWith(report.file_id);
    expect(saveBlob).toHaveBeenCalledWith(blob, "truthlayer-fact-check-annual-report.pdf");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a loading state and ignores repeat clicks while generating", async () => {
    let finish: (v: unknown) => void = () => {};
    downloadReport.mockReturnValue(new Promise((r) => (finish = r)));
    await open(complete());
    await userEvent.click(button());
    expect(button()).toBeDisabled();
    expect(button()).toHaveTextContent("Generating report…");
    expect(button()).toHaveAttribute("aria-busy", "true");
    await userEvent.click(button());
    await userEvent.click(button());
    expect(downloadReport).toHaveBeenCalledTimes(1);
    finish({ blob: new Blob(["x"]), filename: "r.pdf" });
    await waitFor(() => expect(button()).toBeEnabled());
    expect(button()).toHaveTextContent("Download PDF Report");
  });

  it("shows a meaningful error when the download fails, and lets the user retry", async () => {
    downloadReport.mockRejectedValueOnce(new ApiError("report_generation_failed", "The PDF report could not be generated. Please try again."));
    await open(complete());
    await userEvent.click(button());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The PDF report couldn’t be downloaded");
    expect(alert).toHaveTextContent("The PDF report could not be generated. Please try again.");
    expect(saveBlob).not.toHaveBeenCalled();
    expect(button()).toBeEnabled();
    downloadReport.mockResolvedValue({ blob: new Blob(["x"]), filename: "r.pdf" });
    await userEvent.click(button());
    await waitFor(() => expect(saveBlob).toHaveBeenCalled());
    expect(screen.queryByText("The PDF report couldn’t be downloaded")).toBeNull();
  });

  it("explains network failures and the error can be dismissed", async () => {
    downloadReport.mockRejectedValue(new ApiError("network", "Could not reach the TruthLayer backend."));
    await open(complete());
    await userEvent.click(button());
    expect(await screen.findByText("Could not reach the TruthLayer backend.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss error" }));
    expect(screen.queryByText("Could not reach the TruthLayer backend.")).toBeNull();
  });

  it("is available for a document with no claims (the report explains that nothing was found)", async () => {
    await open(makeReport([], { summary: { ...makeReport().summary, narrative: null, needs_investigation: [] } }));
    expect(button()).toBeEnabled();
  });
});
