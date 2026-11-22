"use client";

import { useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Info,
  Loader2,
  UploadCloud,
  X,
} from "lucide-react";
import { ApiError, MAX_UPLOAD_MB, extractPdf, uploadPdf } from "@/lib/api";
import type { ExtractResult } from "@/types";

type Phase = "idle" | "uploading" | "extracting" | "ready" | "error";

interface UploadCardProps {
  onAnalyze: (result: ExtractResult) => void;
  onReset?: () => void;
}

function formatSize(bytes: number) {
  return bytes < 1024 * 1024
    ? `${(bytes / 1024).toFixed(1)} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function UploadCard({ onAnalyze, onReset }: UploadCardProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [dragging, setDragging] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ExtractResult | null>(null);

  const reset = () => {
    abortRef.current?.abort();
    setPhase("idle");
    setFile(null);
    setProgress(0);
    setError(null);
    setResult(null);
    if (inputRef.current) inputRef.current.value = "";
    onReset?.();
  };

  const fail = (message: string) => {
    setError(message);
    setPhase("error");
  };

  const start = async (f?: File) => {
    if (!f) return;
    onReset?.();
    setResult(null);
    setError(null);
    setFile(f);

    if (!f.name.toLowerCase().endsWith(".pdf")) {
      return fail("Only PDF files (.pdf) are supported.");
    }
    if (f.size === 0) return fail("This file is empty.");
    if (f.size > MAX_UPLOAD_MB * 1024 * 1024) {
      return fail(`File is too large. The maximum size is ${MAX_UPLOAD_MB} MB.`);
    }

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      setPhase("uploading");
      setProgress(0);
      const uploaded = await uploadPdf(f, setProgress, controller.signal);
      setPhase("extracting");
      const extracted = await extractPdf(uploaded.file_id);
      setResult(extracted);
      setPhase("ready");
    } catch (e) {
      if (e instanceof ApiError && e.code === "aborted") return;
      fail(e instanceof Error ? e.message : "Something went wrong.");
    }
  };

  const busy = phase === "uploading" || phase === "extracting";

  return (
    <div className="rounded-2xl border border-slate-100 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold text-navy-900">Upload a PDF</h2>
      <p className="mt-1 text-sm text-slate-500">
        Drop a document to extract and verify its factual claims.
      </p>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!busy) start(e.dataTransfer.files?.[0]);
        }}
        className={`mt-5 flex flex-col items-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition ${
          dragging ? "border-sky-brand bg-blue-50" : "border-slate-200 bg-slate-50/50"
        }`}
      >
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-50 text-sky-brand">
          <UploadCloud className="h-7 w-7" />
        </span>
        <p className="mt-4 text-sm font-medium text-navy-900">Drag &amp; drop your PDF here</p>
        <p className="text-xs text-slate-500">or</p>
        <button
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className="mt-2 rounded-xl bg-navy-900 px-5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-navy-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Browse files
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          onChange={(e) => start(e.target.files?.[0])}
        />
      </div>

      {file && (
        <div className="mt-4 rounded-xl border border-slate-100 bg-slate-50 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <span className="flex min-w-0 items-center gap-2 text-sm text-navy-900">
              <FileText className="h-4 w-4 shrink-0 text-sky-brand" />
              <span className="truncate">{file.name}</span>
              <span className="shrink-0 text-xs text-slate-400">{formatSize(file.size)}</span>
            </span>
            <button onClick={reset} aria-label="Remove file">
              <X className="h-4 w-4 text-slate-400 hover:text-slate-700" />
            </button>
          </div>

          {phase === "uploading" && (
            <div className="mt-3" role="status">
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span className="flex items-center gap-1.5">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Uploading…
                </span>
                <span>{progress}%</span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-200">
                <div
                  className="h-full rounded-full bg-sky-brand transition-all"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}

          {phase === "extracting" && (
            <p className="mt-3 flex items-center gap-1.5 text-xs text-slate-500" role="status">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Extracting text…
            </p>
          )}

          {phase === "ready" && result && (
            <p className="mt-3 flex items-center gap-1.5 text-xs font-medium text-green-700" role="status">
              <CheckCircle2 className="h-4 w-4" />
              Upload complete · {result.total_pages} page{result.total_pages === 1 ? "" : "s"} processed
            </p>
          )}

          {phase === "error" && (
            <div className="mt-3 flex items-start gap-2 rounded-lg bg-red-50 p-3 text-xs text-red-700" role="alert">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p className="font-semibold">Couldn&apos;t process this file</p>
                <p className="mt-0.5">{error}</p>
                <button onClick={reset} className="mt-2 font-semibold underline">
                  Choose another file
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <button
        disabled={phase !== "ready" || !result}
        onClick={() => result && onAnalyze(result)}
        className="mt-4 w-full rounded-xl bg-navy-900 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-navy-700 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400 disabled:shadow-none"
      >
        {busy ? "Processing…" : "Analyze document"}
      </button>

      <div className="mt-4 flex items-start gap-2 rounded-xl bg-blue-50 p-3 text-xs text-slate-600">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-sky-brand" />
        <p>
          Supported format: <strong>PDF</strong> (.pdf), up to {MAX_UPLOAD_MB} MB. Text-based PDFs
          work best; scanned (image-only) PDFs need OCR, which is not available yet. Analyze shows
          the extracted text only. Claim checking comes in a later step.
        </p>
      </div>
    </div>
  );
}
