import type { ClaimStatus } from "@/types";

export const STATUS_META: Record<
  ClaimStatus,
  { label: string; badge: string; dot: string; text: string }
> = {
  verified: {
    label: "Verified",
    badge: "bg-green-50 text-green-700 ring-green-600/20",
    dot: "bg-green-500",
    text: "text-green-600",
  },
  inaccurate: {
    label: "Inaccurate",
    badge: "bg-orange-50 text-orange-700 ring-orange-600/20",
    dot: "bg-orange-500",
    text: "text-orange-600",
  },
  false: {
    label: "False",
    badge: "bg-red-50 text-red-700 ring-red-600/20",
    dot: "bg-red-500",
    text: "text-red-600",
  },
  unverified: {
    label: "Unverified",
    badge: "bg-slate-100 text-slate-600 ring-slate-500/20",
    dot: "bg-slate-400",
    text: "text-slate-500",
  },
};

export const STATUS_ORDER: ClaimStatus[] = [
  "verified",
  "inaccurate",
  "false",
  "unverified",
];
