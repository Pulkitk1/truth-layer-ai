import Link from "next/link";
import Logo from "./Logo";

export default function Footer() {
  return (
    <footer className="bg-navy-950 text-slate-300">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-12 sm:px-6 md:grid-cols-3">
        <div>
          <Logo light />
          <p className="mt-3 max-w-xs text-sm text-slate-400">
            AI-powered PDF fact-checking. Don&apos;t just publish. Verify.
          </p>
        </div>
        <div>
          <h4 className="text-sm font-semibold text-white">Product</h4>
          <ul className="mt-3 space-y-2 text-sm">
            <li><Link href="/#features" className="hover:text-white">Features</Link></li>
            <li><Link href="/#how-it-works" className="hover:text-white">How It Works</Link></li>
            <li><Link href="/dashboard" className="hover:text-white">Dashboard</Link></li>
          </ul>
        </div>
        <div>
          <h4 className="text-sm font-semibold text-white">Preview</h4>
          <ul className="mt-3 space-y-2 text-sm">
            <li><Link href="/results" className="hover:text-white">Results</Link></li>
            <li><Link href="/results/demo" className="hover:text-white">Demo Results (sample data)</Link></li>
          </ul>
        </div>
      </div>
      <div className="border-t border-white/10 py-4 text-center text-xs text-slate-500">
        © {new Date().getFullYear()} TruthLayer AI. Results are AI-assisted. Always review the sources.
      </div>
    </footer>
  );
}
