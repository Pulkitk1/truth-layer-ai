import Link from "next/link";
import {
  ArrowRight,
  FileSearch,
  FileText,
  Globe2,
  ScanText,
  ShieldCheck,
  Upload,
} from "lucide-react";
import Navbar from "@/components/Navbar";
import Footer from "@/components/Footer";
import StatusBadge from "@/components/StatusBadge";

const features = [
  {
    icon: ScanText,
    title: "Extract factual claims",
    text: "Automatically pull statistics, dates, names and other checkable claims out of any PDF.",
  },
  {
    icon: Globe2,
    title: "Verify with live web sources",
    text: "Each claim is compared against current, real-world sources instead of stale training data.",
  },
  {
    icon: FileText,
    title: "Detailed fact-checking reports",
    text: "Get a clear verdict, evidence and suggested corrections for every claim in one report.",
  },
];

const steps = [
  { icon: Upload, title: "Upload your PDF", text: "Drag and drop the document you want checked." },
  { icon: FileSearch, title: "Claims are extracted", text: "We identify the statements that can be verified." },
  { icon: Globe2, title: "Claims are verified", text: "Evidence is gathered from live web sources." },
  { icon: ShieldCheck, title: "Review the report", text: "See verdicts, sources and corrections at a glance." },
];

export default function Home() {
  return (
    <>
      <Navbar />
      <main>
        {/* Hero */}
        <section className="bg-gradient-to-b from-blue-50 to-white">
          <div className="mx-auto max-w-6xl px-4 py-20 text-center sm:px-6 sm:py-28">
            <span className="inline-flex items-center gap-2 rounded-full bg-white px-3 py-1 text-xs font-semibold text-navy-700 shadow-sm ring-1 ring-blue-100">
              <ShieldCheck className="h-3.5 w-3.5 text-sky-brand" />
              AI-powered PDF fact-checking
            </span>
            <h1 className="mx-auto mt-6 max-w-3xl text-4xl font-extrabold tracking-tight text-navy-900 sm:text-6xl">
              Don&apos;t Just Publish. <span className="text-sky-brand">Verify.</span>
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-lg text-slate-600">
              TruthLayer AI automatically extracts factual claims from your PDFs and checks
              them against live web sources, so errors never reach your readers.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link
                href="/dashboard"
                className="inline-flex items-center gap-2 rounded-xl bg-navy-900 px-6 py-3 text-sm font-semibold text-white shadow-md transition hover:bg-navy-700"
              >
                Start Fact-Checking <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="#how-it-works"
                className="rounded-xl border border-slate-200 bg-white px-6 py-3 text-sm font-semibold text-navy-900 shadow-sm transition hover:bg-slate-50"
              >
                How It Works
              </Link>
            </div>

            {/* Status legend */}
            <div className="mt-12 flex flex-wrap items-center justify-center gap-2">
              <StatusBadge status="verified" />
              <StatusBadge status="inaccurate" />
              <StatusBadge status="false" />
              <StatusBadge status="unverified" />
            </div>
          </div>
        </section>

        {/* Features */}
        <section id="features" className="mx-auto max-w-6xl scroll-mt-16 px-4 py-20 sm:px-6">
          <h2 className="text-center text-3xl font-bold text-navy-900">Built for trustworthy content</h2>
          <p className="mx-auto mt-3 max-w-xl text-center text-slate-600">
            Everything you need to fact-check a document, end to end.
          </p>
          <div className="mt-12 grid gap-6 md:grid-cols-3">
            {features.map(({ icon: Icon, title, text }) => (
              <div key={title} className="rounded-2xl border border-slate-100 bg-white p-6 shadow-sm transition hover:shadow-md">
                <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 text-sky-brand">
                  <Icon className="h-6 w-6" />
                </span>
                <h3 className="mt-5 text-lg font-semibold text-navy-900">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-600">{text}</p>
              </div>
            ))}
          </div>
        </section>

        {/* How it works */}
        <section id="how-it-works" className="scroll-mt-16 bg-slate-50 py-20">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <h2 className="text-center text-3xl font-bold text-navy-900">How it works</h2>
            <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              {steps.map(({ icon: Icon, title, text }, i) => (
                <div key={title} className="relative rounded-2xl bg-white p-6 shadow-sm">
                  <span className="absolute right-4 top-4 text-3xl font-black text-blue-100">
                    {i + 1}
                  </span>
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-navy-900 text-white">
                    <Icon className="h-5 w-5" />
                  </span>
                  <h3 className="mt-4 font-semibold text-navy-900">{title}</h3>
                  <p className="mt-1 text-sm text-slate-600">{text}</p>
                </div>
              ))}
            </div>
            <div className="mt-10 text-center">
              <Link href="/results/demo" className="text-sm font-semibold text-sky-brand hover:underline">
                Preview the results page (demo data) →
              </Link>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
