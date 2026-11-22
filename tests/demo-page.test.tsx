import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DemoResultsPage from "@/app/results/demo/page";

describe("/results/demo", () => {
  it("is clearly labelled as demo data and offers no PDF download", () => {
    render(<DemoResultsPage />);
    expect(screen.getAllByText(/DEMO DATA/).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /Download PDF Report/ })).toBeNull();
    expect(screen.queryByText(/Download PDF Report/)).toBeNull();
  });
});
