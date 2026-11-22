import { Bell, Search } from "lucide-react";
import Logo from "./Logo";

export default function DashboardTopbar() {
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-4 border-b border-slate-100 bg-white/80 px-4 backdrop-blur sm:px-6">
      <div className="lg:hidden">
        <Logo />
      </div>
      <div className="relative hidden max-w-md flex-1 sm:block">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          type="search"
          placeholder="Search reports…"
          className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-sm outline-none focus:border-sky-brand focus:bg-white"
        />
      </div>
      <div className="flex items-center gap-3">
        <button className="rounded-xl p-2 text-slate-500 hover:bg-slate-50" aria-label="Notifications">
          <Bell className="h-5 w-5" />
        </button>
        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-navy-900 text-sm font-semibold text-white">
          U
        </span>
      </div>
    </header>
  );
}
