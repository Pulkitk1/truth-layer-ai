import { AlertTriangle, FileText, ScanLine } from "lucide-react";
import type { ExtractResult } from "@/types";
import EmptyState from "./EmptyState";

export default function ExtractedTextPreview({ result }: { result: ExtractResult }) {
  const { pages } = result;

  return (
    <section
      id="preview"
      className="scroll-mt-20 rounded-2xl border border-slate-100 bg-white p-6 shadow-sm"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-navy-900">Extracted text preview</h2>
          <p className="mt-1 flex items-center gap-1.5 truncate text-sm text-slate-500">
            <FileText className="h-4 w-4 shrink-0 text-sky-brand" />
            <span className="truncate">{result.filename}</span>
          </p>
        </div>
        <div className="flex gap-2 text-xs">
          <span className="rounded-full bg-blue-50 px-3 py-1 font-semibold text-navy-700">
            {result.total_pages} page{result.total_pages === 1 ? "" : "s"}
          </span>
          {result.empty_pages.length > 0 && (
            <span className="rounded-full bg-orange-50 px-3 py-1 font-semibold text-orange-700">
              {result.empty_pages.length} empty
            </span>
          )}
        </div>
      </div>

      {result.message && (
        <div
          className={`mt-4 flex items-start gap-2 rounded-xl p-3 text-sm ${
            result.ocr_required ? "bg-red-50 text-red-700" : "bg-orange-50 text-orange-800"
          }`}
          role="alert"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>{result.message}</p>
        </div>
      )}

      <div className="mt-5">
        {result.ocr_required ? (
          <EmptyState
            icon={<ScanLine className="h-6 w-6" />}
            title="OCR required"
            description="There is no text layer to show. OCR support is planned for a later step."
          />
        ) : (
          <div className="max-h-[32rem] space-y-4 overflow-y-auto pr-1">
            {pages.map((p) => (
              <article key={p.page_number} className="rounded-xl border border-slate-100">
                <header className="flex items-center justify-between rounded-t-xl bg-slate-50 px-4 py-2 text-xs font-semibold text-slate-500">
                  <span>Page {p.page_number}</span>
                  <span>{p.char_count.toLocaleString()} characters</span>
                </header>
                {p.is_empty ? (
                  <p className="px-4 py-3 text-sm italic text-slate-400">
                    No extractable text on this page.
                  </p>
                ) : (
                  <pre className="whitespace-pre-wrap break-words px-4 py-3 font-sans text-sm leading-relaxed text-slate-700">
                    {p.extracted_text}
                  </pre>
                )}
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
