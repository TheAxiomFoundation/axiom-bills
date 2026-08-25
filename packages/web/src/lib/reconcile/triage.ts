// Triage layer for the reconciliation view: pure functions that rank the
// reconciled sections by how urgently they need attention, so the UI can
// show a prioritized queue instead of a flat grid. No React in here.
//
// Ported from guidance-impact-visualizer's src/lib/diff/triage.ts with the
// two layers renamed documentVsStatute/lawVsModel → billVsLaw/modelVsLaw.
// Scoring semantics are identical: score = (action bonus 100) +
// statusRank*10 + materialityRank, taken as the max over the two layers,
// +1 when either layer records a contested (ambiguous) reading.

import type {
  DiffAction,
  DiffStatus,
  LayerDiff,
  Materiality,
  ReconLayer,
  TopicDiff,
} from "./schema";

// ─── Severity ranking ───────────────────────────────────────────────

export const statusRank: Record<DiffStatus, number> = {
  conflicts: 5,
  missing: 4,
  narrows: 3,
  "adds-detail": 2,
  aligned: 0,
};

export const materialityRank: Record<Materiality, number> = {
  "changes-eligibility": 3,
  "changes-state-duty": 2,
  procedural: 1,
  cosmetic: 0,
  none: 0,
};

export function layerScore(d: LayerDiff): number {
  // api.billReconciliations validates the enums at the fetch boundary;
  // the ?? 0 is defense in depth so an unknown token can never turn a
  // score into NaN (which would make the queue sort arbitrary).
  return (
    (d.action !== "none" ? 100 : 0) +
    (statusRank[d.status] ?? 0) * 10 +
    (materialityRank[d.materiality] ?? 0)
  );
}

// ─── Triage rows ────────────────────────────────────────────────────

// One action-carrying finding: which layer raised it, what kind of gap it
// is, and the combined routing+reason chip label derived from both.
export type TriageFinding = {
  action: Exclude<DiffAction, "none">;
  status: DiffStatus;
  layer: ReconLayer;
  label: string;
};

export type TriagedTopic = {
  topic: TopicDiff;
  section: string;
  actions: DiffAction[]; // distinct non-"none" actions across both layers
  findings: TriageFinding[]; // per-layer action findings, deduped by label
  worstStatus: DiffStatus;
  worstMateriality: Materiality;
  contested: boolean;
  hasAction: boolean;
  score: number;
};

function worstOf<T extends string>(rank: Record<T, number>, a: T, b: T): T {
  return (rank[b] ?? 0) > (rank[a] ?? 0) ? b : a;
}

export function worstStatusOf(a: DiffStatus, b: DiffStatus): DiffStatus {
  return worstOf(statusRank, a, b);
}

export function worstMaterialityOf(a: Materiality, b: Materiality): Materiality {
  return worstOf(materialityRank, a, b);
}

export function triage(topics: TopicDiff[]): TriagedTopic[] {
  const rows = topics.map((topic): TriagedTopic => {
    const layers = [topic.billVsLaw, topic.modelVsLaw];
    const contested = layers.some((d) => Boolean(d.ambiguity));
    const actions: DiffAction[] = [];
    for (const d of layers) {
      if (d.action !== "none" && !actions.includes(d.action)) {
        actions.push(d.action);
      }
    }
    const findings: TriageFinding[] = [];
    for (const layer of ["billVsLaw", "modelVsLaw"] as const) {
      const d = topic[layer];
      if (d.action === "none") continue;
      const label = actionReasonLabel(d.action, d.status);
      if (!findings.some((f) => f.label === label)) {
        findings.push({ action: d.action, status: d.status, layer, label });
      }
    }
    const score = Math.max(...layers.map(layerScore)) + (contested ? 1 : 0);
    return {
      topic,
      section: topic.section,
      actions,
      findings,
      worstStatus: layers
        .map((d) => d.status)
        .reduce((a, b) => worstOf(statusRank, a, b)),
      worstMateriality: layers
        .map((d) => d.materiality)
        .reduce((a, b) => worstOf(materialityRank, a, b)),
      contested,
      hasAction: actions.length > 0,
      score,
    };
  });
  return rows.sort(
    (a, b) => b.score - a.score || a.section.localeCompare(b.section),
  );
}

// ─── Summary counts + filtering ─────────────────────────────────────

export type TriageFilter = "all" | "encode-in-model" | "legal-review" | "aligned";

export function summarize(rows: TriagedTopic[]) {
  return {
    encode: rows.filter((r) => r.actions.includes("encode-in-model")).length,
    legal: rows.filter((r) => r.actions.includes("legal-review")).length,
    aligned: rows.filter((r) => !r.hasAction).length,
    contested: rows.filter((r) => r.contested).length,
  };
}

export function applyFilter(
  rows: TriagedTopic[],
  filter: TriageFilter,
): TriagedTopic[] {
  switch (filter) {
    case "encode-in-model":
    case "legal-review":
      return rows.filter((r) => r.actions.includes(filter));
    case "aligned":
      return rows.filter((r) => !r.hasAction);
    default:
      return rows;
  }
}

// ─── Labels ─────────────────────────────────────────────────────────

export function diffLabel(status: DiffStatus) {
  return status === "adds-detail" ? "adds detail" : status;
}

export function materialityLabel(m: string) {
  switch (m) {
    case "changes-eligibility":
      return "eligibility impact";
    case "changes-state-duty":
      return "state duty";
    case "procedural":
      return "procedural";
    case "cosmetic":
      return "cosmetic";
    default:
      return "";
  }
}

// Combined routing + reason chip, in plain language: encode-in-model
// findings describe the state of the encoding relative to the (amended)
// law; legal-review findings describe what the bill does to the current
// law it amends.
export function actionReasonLabel(action: DiffAction, status: DiffStatus) {
  if (action === "encode-in-model") {
    switch (status) {
      case "missing":
        return "requirement not encoded";
      case "conflicts":
        return "encoded wrong · conflicts with law";
      case "narrows":
        return "encoded too narrowly";
      case "adds-detail":
        return "encoded beyond the law";
      default:
        return "encoding issue";
    }
  }
  if (action === "legal-review") {
    switch (status) {
      case "narrows":
        return "legal · narrows current law";
      case "adds-detail":
        return "legal · expands current law";
      case "conflicts":
        return "legal · conflicts with current law";
      case "missing":
        return "legal · dropped requirement";
      default:
        return "legal review";
    }
  }
  return "";
}
