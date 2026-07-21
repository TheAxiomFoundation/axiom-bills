/**
 * Unit tests for the reconciliation triage layer (ported from
 * guidance-impact-visualizer's diff/triage semantics): severity ranking,
 * the contested (+1) bonus, summary counts, and queue filters.
 */
import { describe, it, expect } from "vitest";
import type { LayerDiff, TopicDiff } from "./schema";
import {
  actionReasonLabel,
  applyFilter,
  diffLabel,
  layerScore,
  materialityLabel,
  materialityRank,
  statusRank,
  summarize,
  triage,
} from "./triage";

function layer(over: Partial<LayerDiff> = {}): LayerDiff {
  return {
    status: "aligned",
    divergence: "none",
    materiality: "none",
    action: "none",
    confidence: "high",
    rationale: "",
    ...over,
  };
}

function topic(
  section: string,
  billVsLaw: Partial<LayerDiff> = {},
  modelVsLaw: Partial<LayerDiff> = {},
): TopicDiff {
  return {
    topic: `Topic ${section}`,
    section,
    billVsLaw: layer(billVsLaw),
    modelVsLaw: layer(modelVsLaw),
  };
}

describe("layerScore", () => {
  it("is 0 for a fully aligned layer", () => {
    expect(layerScore(layer())).toBe(0);
  });

  it("adds 100 for any non-none action", () => {
    expect(layerScore(layer({ action: "encode-in-model" }))).toBe(100);
    expect(layerScore(layer({ action: "legal-review" }))).toBe(100);
  });

  it("is action bonus + statusRank*10 + materialityRank", () => {
    const d = layer({
      status: "conflicts",
      materiality: "changes-eligibility",
      action: "encode-in-model",
    });
    expect(layerScore(d)).toBe(100 + 5 * 10 + 3);
  });

  it("severity orders: conflicts > missing > narrows > adds-detail > aligned", () => {
    expect(statusRank.conflicts).toBeGreaterThan(statusRank.missing);
    expect(statusRank.missing).toBeGreaterThan(statusRank.narrows);
    expect(statusRank.narrows).toBeGreaterThan(statusRank["adds-detail"]);
    expect(statusRank["adds-detail"]).toBeGreaterThan(statusRank.aligned);
  });

  it("materiality orders: eligibility > state duty > procedural > cosmetic = none", () => {
    expect(materialityRank["changes-eligibility"]).toBeGreaterThan(
      materialityRank["changes-state-duty"],
    );
    expect(materialityRank["changes-state-duty"]).toBeGreaterThan(
      materialityRank.procedural,
    );
    expect(materialityRank.procedural).toBeGreaterThan(materialityRank.cosmetic);
    expect(materialityRank.cosmetic).toBe(materialityRank.none);
  });
});

describe("triage", () => {
  it("scores each row as the max over the two layers", () => {
    const rows = triage([
      topic(
        "26 USC 32(a)",
        { status: "adds-detail", materiality: "procedural" }, // 21
        { status: "missing", materiality: "changes-state-duty", action: "encode-in-model" }, // 142
      ),
    ]);
    expect(rows[0].score).toBe(142);
  });

  it("adds +1 when either layer records an ambiguity (contested)", () => {
    const plain = triage([topic("A", { status: "narrows" })])[0];
    const contested = triage([
      topic("A", { status: "narrows", ambiguity: "could read either way" }),
    ])[0];
    expect(plain.contested).toBe(false);
    expect(contested.contested).toBe(true);
    expect(contested.score).toBe(plain.score + 1);
  });

  it("sorts by score descending, then section ascending", () => {
    const rows = triage([
      topic("B"),
      topic("A"),
      topic("C", {}, { status: "conflicts", action: "encode-in-model" }),
    ]);
    expect(rows.map((r) => r.section)).toEqual(["C", "A", "B"]);
  });

  it("the contested bonus breaks ties between otherwise equal rows", () => {
    const rows = triage([
      topic("A", { status: "narrows" }),
      topic("B", { status: "narrows", ambiguity: "alt reading" }),
    ]);
    expect(rows.map((r) => r.section)).toEqual(["B", "A"]);
  });

  it("takes worstStatus and worstMateriality across both layers", () => {
    const row = triage([
      topic(
        "A",
        { status: "narrows", materiality: "changes-eligibility" },
        { status: "conflicts", materiality: "procedural" },
      ),
    ])[0];
    expect(row.worstStatus).toBe("conflicts");
    expect(row.worstMateriality).toBe("changes-eligibility");
  });

  it("collects distinct actions across layers and flags hasAction", () => {
    const row = triage([
      topic(
        "A",
        { status: "narrows", action: "legal-review" },
        { status: "missing", action: "encode-in-model" },
      ),
    ])[0];
    expect(row.actions).toEqual(["legal-review", "encode-in-model"]);
    expect(row.hasAction).toBe(true);

    const aligned = triage([topic("B")])[0];
    expect(aligned.actions).toEqual([]);
    expect(aligned.hasAction).toBe(false);
  });

  it("dedupes findings by label but keeps distinct ones with their layer", () => {
    // Same action+status on both layers → one finding.
    const same = triage([
      topic(
        "A",
        { status: "missing", action: "encode-in-model" },
        { status: "missing", action: "encode-in-model" },
      ),
    ])[0];
    expect(same.findings).toHaveLength(1);
    expect(same.findings[0]).toMatchObject({
      layer: "billVsLaw",
      label: "requirement not encoded",
    });

    // Different labels → two findings, each attributed to its layer.
    const diff = triage([
      topic(
        "B",
        { status: "narrows", action: "legal-review" },
        { status: "missing", action: "encode-in-model" },
      ),
    ])[0];
    expect(diff.findings).toHaveLength(2);
    expect(diff.findings.map((f) => f.layer)).toEqual([
      "billVsLaw",
      "modelVsLaw",
    ]);
  });
});

describe("summarize", () => {
  it("counts each queue independently (a row can be in several)", () => {
    const rows = triage([
      topic(
        "A",
        { status: "narrows", action: "legal-review", ambiguity: "alt" },
        { status: "missing", action: "encode-in-model" },
      ),
      topic("B", {}, { status: "missing", action: "encode-in-model" }),
      topic("C"),
      topic("D"),
    ]);
    expect(summarize(rows)).toEqual({
      encode: 2,
      legal: 1,
      aligned: 2,
      contested: 1,
    });
  });
});

describe("applyFilter", () => {
  const rows = triage([
    topic(
      "A",
      { status: "narrows", action: "legal-review" },
      { status: "missing", action: "encode-in-model" },
    ),
    topic("B", {}, { status: "missing", action: "encode-in-model" }),
    topic("C"),
  ]);

  it("'all' returns every row", () => {
    expect(applyFilter(rows, "all")).toHaveLength(3);
  });

  it("'encode-in-model' keeps rows carrying that action", () => {
    expect(applyFilter(rows, "encode-in-model").map((r) => r.section).sort())
      .toEqual(["A", "B"]);
  });

  it("'legal-review' keeps rows carrying that action", () => {
    expect(applyFilter(rows, "legal-review").map((r) => r.section)).toEqual(["A"]);
  });

  it("'aligned' keeps only rows with no action at all", () => {
    expect(applyFilter(rows, "aligned").map((r) => r.section)).toEqual(["C"]);
  });
});

describe("labels", () => {
  it("diffLabel humanizes adds-detail only", () => {
    expect(diffLabel("adds-detail")).toBe("adds detail");
    expect(diffLabel("conflicts")).toBe("conflicts");
  });

  it("materialityLabel maps the enum and blanks 'none'", () => {
    expect(materialityLabel("changes-eligibility")).toBe("eligibility impact");
    expect(materialityLabel("changes-state-duty")).toBe("state duty");
    expect(materialityLabel("none")).toBe("");
  });

  it("actionReasonLabel combines routing and reason", () => {
    expect(actionReasonLabel("encode-in-model", "missing")).toBe(
      "requirement not encoded",
    );
    expect(actionReasonLabel("legal-review", "narrows")).toBe(
      "legal · narrows current law",
    );
    expect(actionReasonLabel("none", "aligned")).toBe("");
  });
});
