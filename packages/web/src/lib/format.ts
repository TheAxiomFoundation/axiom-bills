import type { NormalizedStatus } from "./api";

export const STATUS_LABEL: Record<NormalizedStatus, string> = {
  introduced:      "Introduced",
  in_committee:    "In committee",
  passed_chamber:  "Passed one chamber",
  passed_both:     "Passed both chambers",
  enrolled:        "Sent to executive",
  signed:          "Signed",
  enacted:         "Enacted",
  vetoed:          "Vetoed",
  veto_overridden: "Veto overridden",
  failed:          "Failed",
  unknown:         "—",
};

export const STATUS_COLOR: Record<NormalizedStatus, string> = {
  introduced:      "#64748b",
  in_committee:    "#94a3b8",
  passed_chamber:  "#3b82f6",
  passed_both:     "#1d4ed8",
  enrolled:        "#a855f7",
  signed:          "#10b981",
  enacted:         "#059669",
  vetoed:          "#ef4444",
  veto_overridden: "#f59e0b",
  failed:          "#475569",
  unknown:         "#cbd5e1",
};

export function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    year: "numeric", month: "short", day: "numeric",
  });
}
