import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeReport } from "./fixtures";

let search = "";
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(search) }));

const getReport = vi.fn();
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, getReport: (...a: unknown[]) => getReport(...a), generateSummary: vi.fn().mockResolvedValue(makeReport()) };
});

import ResultsPage from "@/app/results/page";

beforeEach(() => {
  getReport.mockReset();
  window.localStorage.clear();
  search = "";
});

describe("/results page", () => {
  it("shows an empty state with a link to upload (and the labelled demo) when no document is known", async () => {
    render(<ResultsPage />);
    expect(await screen.findByText("No results yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Upload a PDF/ })).toHaveAttribute("href", "/dashboard");
    expect(screen.getByRole("link", { name: /demo data/ })).toHaveAttribute("href", "/results/demo");
    expect(getReport).not.toHaveBeenCalled();
  });

  it("loads the document named in the URL and remembers it", async () => {
    search = "file=" + "e".repeat(32);
    getReport.mockResolvedValue(makeReport());
    render(<ResultsPage />);
    expect(await screen.findByTestId("document-name")).toHaveTextContent("annual-report.pdf");
    expect(getReport).toHaveBeenCalledWith("e".repeat(32));
    expect(window.localStorage.getItem("truthlayer:lastFileId")).toBe("e".repeat(32));
  });

  it("falls back to the last document opened in this browser", async () => {
    window.localStorage.setItem("truthlayer:lastFileId", "c".repeat(32));
    getReport.mockResolvedValue(makeReport());
    render(<ResultsPage />);
    expect(await screen.findByTestId("document-name")).toBeInTheDocument();
    expect(getReport).toHaveBeenCalledWith("c".repeat(32));
  });
});
