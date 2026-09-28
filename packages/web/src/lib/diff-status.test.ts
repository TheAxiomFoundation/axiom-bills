import { describe, it, expect } from "vitest";
import { diffTabStatus, opsSummary, unappliedListPromise } from "./diff-status";
import type { AmendmentOp } from "./api";

const op = (over: Partial<AmendmentOp> = {}): AmendmentOp => ({
  kind: "strike-insert",
  needle: "$3,000",
  payload: "$1",
  raw: "by striking ``$3,000'' and inserting ``$1''",
  ...over,
});

describe("diffTabStatus", () => {
  it("counts applied edits", () => {
    expect(diffTabStatus({ applied_ops: [op()], unapplied_ops: [], in_corpus: true }))
      .toEqual({ tone: "applied", label: "1 edit" });
    expect(diffTabStatus({ applied_ops: [op(), op()], unapplied_ops: [], in_corpus: true }).label)
      .toBe("2 edits");
  });

  it("says 'not applied', never 'unparsed', for an instruction the parser produced", () => {
    // S. 3596 §2(a): the strike-insert parsed; the scope could not be located.
    const status = diffTabStatus({
      applied_ops: [],
      unapplied_ops: [op({ note: "corpus has no row for 26 USC 24(d)(1)(B)(i)" })],
      in_corpus: true,
    });
    expect(status).toEqual({ tone: "unapplied", label: "not applied" });
  });

  it("does not let applied edits hide unapplied ones", () => {
    expect(diffTabStatus({ applied_ops: [op(), op()], unapplied_ops: [op()], in_corpus: true }))
      .toEqual({ tone: "unapplied", label: "2 edits, 1 not applied" });
  });

  it("distinguishes missing corpus text from an untouched section", () => {
    expect(diffTabStatus({ applied_ops: [], unapplied_ops: [], in_corpus: false }).label)
      .toBe("no corpus text");
    expect(diffTabStatus({ applied_ops: [], unapplied_ops: [], in_corpus: true }).label)
      .toBe("no diff detected");
  });
});

describe("opsSummary", () => {
  it("names both counts", () => {
    expect(opsSummary({ applied_ops: [op()], unapplied_ops: [op(), op()], in_corpus: true }))
      .toBe("1 applied, 2 not applied");
  });
});

describe("unappliedListPromise", () => {
  it("promises a reason for each only when each has one", () => {
    expect(unappliedListPromise({ unapplied_ops: [op({ note: "needle not found" })] }))
      .toContain("each with the reason");
  });

  it("promises nothing about reasons for diffs stored before notes existed", () => {
    expect(unappliedListPromise({ unapplied_ops: [op(), op({ note: "  " })] }))
      .toBe("The instructions are listed below.");
  });

  it("says so when only some carry a reason", () => {
    expect(unappliedListPromise({ unapplied_ops: [op({ note: "ambiguous" }), op()] }))
      .toContain("where one was recorded");
  });
});

