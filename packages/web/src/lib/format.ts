import type { BillKind, NormalizedStatus } from "./api";

export const KIND_LABEL: Record<BillKind, string> = {
  substantive:    "Substantive",
  placeholder:    "Placeholder",
  ceremonial:     "Ceremonial",
  appropriations: "Appropriations",
  procedural:     "Procedural",
  vehicle:        "Vehicle",
  unknown:        "Unclassified",
};

export const KIND_DESC: Record<BillKind, string> = {
  substantive:    "Real policy change — what the encoder cares about.",
  placeholder:    "Reserved bill number, no text yet.",
  ceremonial:     "Post-office namings, sense-of-the-House, commemorations.",
  appropriations: "Spending bills.",
  procedural:     "Chamber rules, consideration motions, leadership elections.",
  vehicle:        "Strip-and-replace shell bill.",
  unknown:        "Did not match any classifier rule.",
};

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

// Axiom editorial palette: ink-muted for early/inert states, burnt-sienna
// accent for in-flight progress, success-green for enacted, error red for
// vetoed. Badges paint border + text (currentColor) on the paper background.
export const STATUS_COLOR: Record<NormalizedStatus, string> = {
  introduced:      "#78716c", // ink-muted
  in_committee:    "#78716c",
  passed_chamber:  "#92400e", // accent
  passed_both:     "#92400e",
  enrolled:        "#92400e",
  signed:          "#166534", // success
  enacted:         "#166534",
  vetoed:          "#991b1b", // error
  veto_overridden: "#92400e",
  failed:          "#78716c",
  unknown:         "#a8a29e",
};

export function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    year: "numeric", month: "short", day: "numeric",
  });
}
