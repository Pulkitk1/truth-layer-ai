import { CheckCircle2, HelpCircle } from "lucide-react";
import type { VerificationResult } from "@/types";

const join = (...parts: (string | null | undefined)[]) => parts.filter(Boolean).join(" ");

/**
 * Original vs. corrected information for an INACCURATE or FALSE claim.
 * A correction is shown only when the backend confirmed it against a cited source ("confirmed");
 * otherwise the user is told that no reliable correction could be established.
 */
export default function CorrectionBox({ result }: { result: VerificationResult }) {
  const status = result.verification_status;
  if (status !== "INACCURATE" && status !== "FALSE") return null;
  const tone =
    status === "FALSE"
      ? { box: "bg-red-50 ring-red-200/60", head: "text-red-700", orig: "text-red-700", chip: "bg-red-100 text-red-700" }
      : { box: "bg-orange-50 ring-orange-200/60", head: "text-orange-700", orig: "text-orange-700", chip: "bg-orange-100 text-orange-700" };

  if (result.correction_status !== "confirmed") {
    return (
      <section aria-label="Correct information" className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200">
        <h4 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          <HelpCircle className="h-3.5 w-3.5" /> Correct information
        </h4>
        <p className="mt-1 text-sm text-slate-600">
          A reliable corrected figure could not be confirmed from the evidence collected, so none is shown.
        </p>
      </section>
    );
  }

  const original = join(result.original_value, result.unit) || "As stated in the claim";
  const corrected = join(result.corrected_value, result.unit);
  return (
    <section aria-label="Correct information" className={`rounded-xl p-3 ring-1 ring-inset ${tone.box}`}>
      <h4 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-green-700">
        <CheckCircle2 className="h-3.5 w-3.5" /> Correct information
      </h4>
      <div className="mt-2 grid grid-cols-2 gap-2" aria-label="Comparison">
        <div className="rounded-lg bg-white/70 p-2.5">
          <p className={`text-[10px] font-semibold uppercase tracking-wide ${tone.orig}`}>In the PDF</p>
          <p className="mt-0.5 break-words text-base font-bold text-slate-500 line-through decoration-1">{original}</p>
        </div>
        <div className="rounded-lg bg-white p-2.5 ring-1 ring-green-300/70">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-green-700">Evidence says</p>
          <p className="mt-0.5 break-words text-base font-bold text-green-800">{corrected}</p>
          <p className="mt-0.5 text-[11px] text-slate-500">
            {result.reference_period ? `Reference period: ${result.reference_period}` : "Reference period not stated"}
          </p>
        </div>
      </div>
      {result.corrected_claim && <p className="mt-2 text-sm font-medium text-slate-800">{result.corrected_claim}</p>}
      {result.correction_explanation && (
        <p className="mt-1.5 text-xs leading-relaxed text-slate-600">
          <span className="font-semibold">Why this is right: </span>
          {result.correction_explanation}
        </p>
      )}
    </section>
  );
}
