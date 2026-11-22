import Link from "next/link";
import { ShieldCheck } from "lucide-react";

export default function Logo({ light = false }: { light?: boolean }) {
  return (
    <Link href="/" className="flex items-center gap-2">
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-navy-900 text-white shadow-sm">
        <ShieldCheck className="h-5 w-5" />
      </span>
      <span
        className={`text-lg font-bold tracking-tight ${
          light ? "text-white" : "text-navy-900"
        }`}
      >
        TruthLayer <span className="text-sky-brand">AI</span>
      </span>
    </Link>
  );
}
