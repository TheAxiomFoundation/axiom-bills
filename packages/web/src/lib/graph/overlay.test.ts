/**
 * Unit tests for the bill → graph overlay join.
 *
 * The graph fixture mimics what `precompute-graph` stores in
 * bills.encoding_graphs: every section layer "baseline", ids = citations
 * derived from rulespec file paths.
 */
import { describe, it, expect } from "vitest";
import type { BillDiffs, BillDiffSection } from "../api";
import type { RulespecGraph, SectionNode } from "./rulespec-graph";
import { billOverlay, citationFromFilePath, focusOnBill } from "./overlay";
import { buildAdjacency, layoutPositions, lineageSet } from "./rulespec-graph";

function section(over: Partial<SectionNode> & { id: string }): SectionNode {
  return {
    legalId: over.id,
    label: over.id,
    group: "statutes/26",
    layer: "baseline",
    summary: "",
    ruleCount: 1,
    rules: [],
    deferred: [],
    ...over,
  };
}

const GRAPH: RulespecGraph = {
  meta: {
    program: "test",
    generatedFrom: "rulespec-us@abc123",
    statuteCitation: "",
    guidanceCitation: "",
    extractedAt: "2026-01-01T00:00:00Z",
    note: "",
    counts: {
      sections: 3, rules: 3, guidanceSections: 0, guidanceRules: 0,
      deferredOutputs: 0, edges: 2,
    },
  },
  groups: [{ id: "statutes/26", label: "Title 26" }],
  sections: [
    section({ id: "26 USC 32", legalId: "26 U.S.C. § 32" }),
    section({ id: "26 USC 152" }),
    section({ id: "7 CFR 273.3", group: "regulations/7-cfr/273" }),
  ],
  edges: [
    { from: "26 USC 152", to: "26 USC 32", type: "import", via: "dependent" },
    { from: "26 USC 32", to: "7 CFR 273.3", type: "reference" },
  ],
};

function diffSection(over: Partial<BillDiffSection> & { citation: string }): BillDiffSection {
  return {
    in_corpus: true,
    exact_corpus_match: true,
    sliced_subsection: false,
    matched_corpus_path: null,
    heading: null,
    current_text: null,
    applied_text: null,
    diff: [],
    applied_ops: [],
    unapplied_ops: [],
    has_rulespec: false,
    encoding: null,
    axiom_url: null,
    source_url: null,
    ...over,
  };
}

function encoding(citation: string, file_path: string) {
  return {
    repo: "rulespec-us",
    kind: "statute" as const,
    citation,
    file_path,
    github_url: "https://example.test",
  };
}

const BILL = { number: "HR 1234", title: "An act to amend the EITC" };

describe("citationFromFilePath", () => {
  it("parses statute paths, with and without subsections", () => {
    expect(citationFromFilePath("statutes/26/32.yaml")).toBe("26 USC 32");
    expect(citationFromFilePath("statutes/26/32/a/1.yaml")).toBe("26 USC 32(a)(1)");
    expect(citationFromFilePath("statutes/26/45A.yaml")).toBe("26 USC 45A");
  });

  it("parses regulation paths", () => {
    expect(citationFromFilePath("regulations/7-cfr/273/3.yaml")).toBe("7 CFR 273.3");
  });

  it("parses policy paths for traceability", () => {
    expect(citationFromFilePath("policies/usda/snap/fy-2026-cola.yaml"))
      .toBe("policy:usda/snap/fy-2026-cola");
  });

  it("rejects unrecognized paths", () => {
    expect(citationFromFilePath("README.md")).toBeNull();
    expect(citationFromFilePath("statutes/appendix/32.yaml")).toBeNull();
    expect(citationFromFilePath("regulations/7/273/3.yaml")).toBeNull();
  });
});

describe("billOverlay", () => {
  it("marks a section touched when encoding.citation matches a node id", () => {
    const diffs: BillDiffs = {
      sections: [
        diffSection({
          citation: "26 USC 32(b)",
          encoding: encoding("26 USC 32", "statutes/26/32.yaml"),
        }),
      ],
    };
    const out = billOverlay(GRAPH, diffs, BILL);
    const touched = out.sections.find((s) => s.id === "26 USC 32");
    expect(touched?.layer).toBe("bill");
    // The other sections stay baseline.
    expect(out.sections.find((s) => s.id === "26 USC 152")?.layer).toBe("baseline");
    expect(out.diffCitationById["26 USC 32"]).toBe("26 USC 32(b)");
  });

  it("falls back to the file-path-derived citation when encoding.citation differs", () => {
    const diffs: BillDiffs = {
      sections: [
        diffSection({
          citation: "7 USC 2015(o)",
          // citation string doesn't match any node, but the file path does
          encoding: encoding("some other form", "regulations/7-cfr/273/3.yaml"),
        }),
      ],
    };
    const out = billOverlay(GRAPH, diffs, BILL);
    expect(out.sections.find((s) => s.id === "7 CFR 273.3")?.layer).toBe("bill");
  });

  it("matches against legalId too", () => {
    const diffs: BillDiffs = {
      sections: [
        diffSection({
          citation: "26 USC 32",
          encoding: encoding("26 U.S.C. § 32", "elsewhere/32.yaml"),
        }),
      ],
    };
    const out = billOverlay(GRAPH, diffs, BILL);
    expect(out.sections.find((s) => s.id === "26 USC 32")?.layer).toBe("bill");
  });

  it("adds a synthetic bill node with implements edges into touched sections", () => {
    const diffs: BillDiffs = {
      sections: [
        diffSection({
          citation: "26 USC 32(b)",
          encoding: encoding("26 USC 32", "statutes/26/32.yaml"),
        }),
        diffSection({
          citation: "26 USC 152(c)",
          encoding: encoding("26 USC 152", "statutes/26/152.yaml"),
        }),
      ],
    };
    const out = billOverlay(GRAPH, diffs, BILL);
    expect(out.billNodeId).toBe("HR 1234");
    const billNode = out.sections.find((s) => s.id === "HR 1234");
    expect(billNode?.layer).toBe("statute");
    expect(billNode?.label).toBe("An act to amend the EITC");
    const implEdges = out.edges.filter((e) => e.type === "implements");
    expect(implEdges).toEqual([
      { from: "HR 1234", to: "26 USC 32", type: "implements" },
      { from: "HR 1234", to: "26 USC 152", type: "implements" },
    ]);
    // Original graph edges are preserved.
    expect(out.edges.filter((e) => e.type !== "implements")).toEqual(GRAPH.edges);
  });

  it("dedupes multiple diff sections landing on the same node, keeping the first citation", () => {
    const diffs: BillDiffs = {
      sections: [
        diffSection({
          citation: "26 USC 32(a)",
          encoding: encoding("26 USC 32", "statutes/26/32.yaml"),
        }),
        diffSection({
          citation: "26 USC 32(m)",
          encoding: encoding("26 USC 32", "statutes/26/32.yaml"),
        }),
      ],
    };
    const out = billOverlay(GRAPH, diffs, BILL);
    expect(out.edges.filter((e) => e.type === "implements")).toHaveLength(1);
    expect(out.diffCitationById["26 USC 32"]).toBe("26 USC 32(a)");
  });

  it("turns encoding_backlog sections into dashed placeholder nodes off the bill node", () => {
    const diffs: BillDiffs = {
      sections: [
        diffSection({
          citation: "26 USC 32(b)",
          encoding: encoding("26 USC 32", "statutes/26/32.yaml"),
        }),
        diffSection({
          citation: "26 USC 6428B",
          heading: "2026 recovery rebates",
          encoding_backlog: true,
        }),
        // duplicate backlog citation must not create a second node
        diffSection({ citation: "26 USC 6428B", encoding_backlog: true }),
      ],
    };
    const out = billOverlay(GRAPH, diffs, BILL);
    const placeholders = out.sections.filter((s) => s.layer === "placeholder");
    expect(placeholders).toHaveLength(1);
    expect(placeholders[0].id).toBe("26 USC 6428B");
    expect(placeholders[0].label).toBe("2026 recovery rebates");
    expect(placeholders[0].ruleCount).toBe(0);
    expect(out.edges).toContainEqual({
      from: "HR 1234", to: "26 USC 6428B", type: "implements",
    });
  });

  it("treats a backlog citation already present in the graph as touched, never a duplicate node", () => {
    // Snapshot skew: the graph job encoded "26 USC 152" after the
    // bill's diffs were computed with encoding_backlog still set.
    const diffs: BillDiffs = {
      sections: [
        diffSection({ citation: "26 USC 152", encoding_backlog: true }),
      ],
    };
    const out = billOverlay(GRAPH, diffs, BILL);
    const ids = out.sections.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length); // no duplicate node ids
    expect(out.sections.filter((s) => s.layer === "placeholder")).toHaveLength(0);
    const node = out.sections.find((s) => s.id === "26 USC 152");
    expect(node?.layer).toBe("bill");
    expect(out.edges).toContainEqual({
      from: "HR 1234", to: "26 USC 152", type: "implements",
    });
    expect(out.diffCitationById["26 USC 152"]).toBe("26 USC 152");
  });

  it("creates a bill node for a backlog-only bill (needs_new_encoding, no matches)", () => {
    const diffs: BillDiffs = {
      sections: [
        diffSection({ citation: "26 USC 6428B", encoding_backlog: true }),
      ],
    };
    const out = billOverlay(GRAPH, diffs, BILL);
    expect(out.billNodeId).toBe("HR 1234");
    expect(out.sections.filter((s) => s.layer === "placeholder")).toHaveLength(1);
  });

  it("returns the graph unchanged (no bill node) when nothing matches", () => {
    const diffs: BillDiffs = {
      sections: [
        // reference-only section: no encoding, no backlog flag
        diffSection({ citation: "42 USC 1396a" }),
        // encoded but against a file this graph doesn't contain
        diffSection({
          citation: "8 USC 1613",
          encoding: encoding("8 USC 1613", "statutes/8/1613.yaml"),
        }),
      ],
    };
    const out = billOverlay(GRAPH, diffs, BILL);
    expect(out.billNodeId).toBeNull();
    expect(out.sections).toHaveLength(GRAPH.sections.length);
    expect(out.sections.every((s) => s.layer === "baseline")).toBe(true);
    expect(out.edges).toEqual(GRAPH.edges);
  });

  it("does not mutate the input graph", () => {
    const diffs: BillDiffs = {
      sections: [
        diffSection({
          citation: "26 USC 32(b)",
          encoding: encoding("26 USC 32", "statutes/26/32.yaml"),
        }),
      ],
    };
    billOverlay(GRAPH, diffs, BILL);
    expect(GRAPH.sections.every((s) => s.layer === "baseline")).toBe(true);
    expect(GRAPH.edges).toHaveLength(2);
    expect(GRAPH.sections).toHaveLength(3);
  });
});

describe("lineage helpers", () => {
  it("BFS reaches ancestors and descendants but not siblings' branches", () => {
    const edges = [
      { from: "a", to: "b" },
      { from: "b", to: "c" },
      { from: "x", to: "c" }, // c's other parent — upstream of c, not of b
      { from: "b", to: "d" },
    ];
    const adj = buildAdjacency(edges);
    expect(lineageSet("b", adj)).toEqual(new Set(["a", "b", "c", "d"]));
    expect(lineageSet("x", adj)).toEqual(new Set(["x", "c"]));
  });

  it("layoutPositions places every node and ignores dangling edges", () => {
    const pos = layoutPositions(
      ["a", "b"],
      [{ from: "a", to: "b" }, { from: "a", to: "ghost" }],
    );
    expect(pos.size).toBe(2);
    // rankdir LR: the dependent sits to the right of its dependency.
    expect(pos.get("b")!.x).toBeGreaterThan(pos.get("a")!.x);
  });
});

describe("focusOnBill", () => {
  // Wider graph: an island unrelated to the touched section, plus the
  // 3-node lineage chain the bill lands in.
  const WIDE: RulespecGraph = {
    ...GRAPH,
    sections: [
      ...GRAPH.sections,
      section({ id: "42 USC 1396a", group: "statutes/42" }),
      section({ id: "42 USC 1396d", group: "statutes/42" }),
    ],
    edges: [
      ...GRAPH.edges,
      { from: "42 USC 1396a", to: "42 USC 1396d", type: "import" },
    ],
  };

  it("keeps the touched lineage and drops unrelated islands", () => {
    const diffs: BillDiffs = {
      sections: [
        diffSection({
          citation: "26 USC 32",
          has_rulespec: true,
          encoding: encoding("26 USC 32", "statutes/26/32.yaml"),
        }),
      ],
    };
    const out = focusOnBill(billOverlay(WIDE, diffs, BILL));
    const ids = out.sections.map((s) => s.id);
    expect(ids).toContain("26 USC 32");        // touched
    expect(ids).toContain("26 USC 152");       // upstream lineage
    expect(ids).toContain("7 CFR 273.3");      // downstream lineage
    expect(ids).toContain(BILL.number);        // synthetic bill node
    expect(ids).not.toContain("42 USC 1396a"); // unrelated island
    expect(ids).not.toContain("42 USC 1396d");
    for (const e of out.edges) {
      expect(ids).toContain(e.from);
      expect(ids).toContain(e.to);
    }
  });

  it("is a no-op when the bill touches nothing", () => {
    const diffs: BillDiffs = { sections: [] };
    const overlay = billOverlay(WIDE, diffs, BILL);
    expect(focusOnBill(overlay)).toBe(overlay);
  });
});
