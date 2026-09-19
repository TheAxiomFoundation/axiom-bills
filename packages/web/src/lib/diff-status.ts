// What a section's tab says about its amendment instructions.
//
// An instruction can fail at two different points, and the tab used to
// call both "unparsed". S. 3596's strike of "$3,000" parsed cleanly; what
// failed was locating clause (B)(i) inside the corpus row. Saying
// "unparsed" sent readers looking for a grammar problem that was not
// there. An instruction the parser produced but could not apply is
// "not applied"; the reason travels with it in `note`.
import type { BillDiffSection } from "./api";

export type DiffTabTone = "applied" | "unapplied" | "noop";

export type DiffTabStatus = { tone: DiffTabTone; label: string };

type Counts = Pick<BillDiffSection, "applied_ops" | "unapplied_ops" | "in_corpus">;

export function diffTabStatus(section: Counts): DiffTabStatus {
  const applied = section.applied_ops.length;
  const unapplied = section.unapplied_ops.length;
  if (applied > 0) {
    const edits = `${applied} edit${applied === 1 ? "" : "s"}`;
    // A section with both must not read as fully applied.
    return unapplied > 0
      ? { tone: "unapplied", label: `${edits}, ${unapplied} not applied` }
      : { tone: "applied", label: edits };
  }
  if (unapplied > 0) return { tone: "unapplied", label: "not applied" };
  if (!section.in_corpus) return { tone: "noop", label: "no corpus text" };
  return { tone: "noop", label: "no diff detected" };
}

export function opsSummary(section: Counts): string {
  return `${section.applied_ops.length} applied, ${section.unapplied_ops.length} not applied`;
}

// What the hint may promise about the list below it. Diffs computed
// before reasons were recorded, and instructions whose section is not in
// corpus at all, carry no `note`; the hint must not say each one comes
// with a reason when some do not.
export function unappliedListPromise(
  section: Pick<BillDiffSection, "unapplied_ops">,
): string {
  const ops = section.unapplied_ops;
  const withReason = ops.filter((op) => (op.note ?? "").trim() !== "").length;
  if (withReason === ops.length) {
    return "The instructions are listed below, each with the reason it was not applied.";
  }
  if (withReason === 0) return "The instructions are listed below.";
  return "The instructions are listed below, with the reason where one was recorded.";
}

