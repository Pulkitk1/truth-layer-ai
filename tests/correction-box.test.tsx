import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import CorrectionBox from "@/components/CorrectionBox";
import type { VerificationResult } from "@/types";
import { CLAIMS } from "./fixtures";

const base = CLAIMS[2].verification as VerificationResult;
const make = (o: Partial<VerificationResult>): VerificationResult => ({ ...base, ...o });

describe("CorrectionBox", () => {
  it("shows the original and corrected figures side by side with unit and period", () => {
    render(<CorrectionBox result={make({ verification_status: "FALSE" })} />);
    const cmp = screen.getByLabelText("Comparison");
    expect(cmp).toHaveTextContent("10 million units");
    expect(cmp).toHaveTextContent("14 million units");
    expect(cmp).toHaveTextContent("Reference period: 2023");
    expect(screen.getByText(/The source reports 14 million units/)).toBeInTheDocument();
  });

  it("says no correction could be confirmed instead of showing a figure", () => {
    render(<CorrectionBox result={make({ correction_status: "not_confirmed", corrected_value: null, corrected_claim: null })} />);
    expect(screen.getByText(/could not be confirmed/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Comparison")).toBeNull();
  });

  it("does not render for verified, unverified or hypothetical claims", () => {
    for (const s of ["VERIFIED", "UNVERIFIED"] as const) {
      const { container } = render(<CorrectionBox result={make({ verification_status: s, correction_status: "not_applicable" })} />);
      expect(container).toBeEmptyDOMElement();
    }
  });

  it("uses red for FALSE and orange for INACCURATE", () => {
    const { container: f } = render(<CorrectionBox result={make({ verification_status: "FALSE" })} />);
    expect(f.innerHTML).toContain("bg-red-50");
    const { container: i } = render(<CorrectionBox result={make({ verification_status: "INACCURATE" })} />);
    expect(i.innerHTML).toContain("bg-orange-50");
  });
});
