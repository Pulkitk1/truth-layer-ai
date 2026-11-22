"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, FileText, LayoutDashboard, Upload, Home } from "lucide-react";
import Logo from "./Logo";

const items = [
  { href: "/dashboard", label: "Upload", icon: Upload },
  { href: "/results", label: "Results", icon: BarChart3 },
  { href: "/results/demo", label: "Demo Data", icon: LayoutDashboard },
  { href: "/dashboard#reports", label: "Recent Reports", icon: FileText },
  { href: "/", label: "Home", icon: Home },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <>
      {/* Desktop sidebar */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-100 bg-white p-4 lg:flex">
        <div className="px-2 py-2">
          <Logo />
        </div>
        <nav className="mt-6 space-y-1">
          {items.map(({ href, label, icon: Icon }) => {
            const active = href === pathname;
            return (
              <Link
                key={label}
                href={href}
                className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition ${
                  active
                    ? "bg-blue-50 text-navy-900"
                    : "text-slate-600 hover:bg-slate-50"
                }`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto rounded-2xl bg-blue-50 p-4 text-xs text-slate-600">
          <p className="font-semibold text-navy-900">Real vs demo data</p>
          <p className="mt-1">“Demo Data” pages show sample data only. Real results are under “Results”.</p>
        </div>
      </aside>

      {/* Mobile tab bar */}
      <nav className="fixed inset-x-0 bottom-0 z-40 flex justify-around border-t border-slate-100 bg-white py-2 lg:hidden">
        {items.map(({ href, label, icon: Icon }) => (
          <Link
            key={label}
            href={href}
            className={`flex flex-col items-center gap-0.5 px-3 text-[11px] font-medium ${
              href === pathname ? "text-navy-900" : "text-slate-500"
            }`}
          >
            <Icon className="h-5 w-5" />
            {label.replace("Recent ", "")}
          </Link>
        ))}
      </nav>
    </>
  );
}
