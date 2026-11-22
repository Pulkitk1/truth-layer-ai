import type { ReactNode } from "react";

interface StatCardProps {
  label: string;
  value: number | string;
  icon?: ReactNode;
  accent?: string; // tailwind text color class
  active?: boolean;
  onClick?: () => void;
  className?: string;
}

export default function StatCard({
  label,
  value,
  icon,
  accent = "text-navy-900",
  active,
  onClick,
  className = "",
}: StatCardProps) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      onClick={onClick}
      className={`rounded-2xl border bg-white p-4 text-left shadow-sm transition ${
        active ? "border-sky-brand ring-2 ring-blue-100" : "border-slate-100"
      } ${onClick ? "cursor-pointer hover:shadow-md" : ""} ${className}`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-500">{label}</span>
        <span className={accent}>{icon}</span>
      </div>
      <div className={`mt-2 text-3xl font-bold ${accent}`}>{value}</div>
    </Tag>
  );
}
