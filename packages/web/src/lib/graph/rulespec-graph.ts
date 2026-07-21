// Types + pure helpers for the RuleSpec section dependency graph.
//
// The graph JSON is produced by the scrapers' `precompute-graph` command
// (one row per rulespec repo in bills.encoding_graphs) and follows the
// contract of the guidance-impact-visualizer this UI is ported from:
// meta / groups / sections / edges. Every *stored* section has
// layer "baseline"; the other layers are assigned client-side by the
// bill overlay (see ./overlay.ts).
//
// Everything in this module is framework-free (no React) so the layout
// and lineage logic can be unit-tested and reused.

import dagre from "dagre";

export type SectionLayer =
  | "baseline" // stored encoding, untouched by the bill
  | "guidance" // reserved by the shared contract (unused here)
  | "statute" // synthetic anchor node (the bill itself)
  | "bill" // encoded section the bill amends
  | "placeholder"; // amended-but-not-yet-encoded backlog citation

export type RuleSummary = {
  name: string;
  kind: string; // parameter | derived | ...
  dtype: string | null;
  period: string | null;
  source: string | null;
};

export type DeferredOutput = {
  output: string;
  reason: string;
  source: string | null;
};

export type SectionNode = {
  id: string; // "26 USC 32" | "7 CFR 273.3"
  legalId: string;
  label: string;
  group: string;
  layer: SectionLayer;
  summary: string;
  ruleCount: number;
  rules: RuleSummary[];
  deferred: DeferredOutput[];
};

export type SectionEdge = {
  from: string;
  to: string;
  type: "import" | "reference" | "implements";
  via?: string; // imported rule name, when known
};

export type RulespecGraph = {
  meta: {
    program: string;
    generatedFrom: string;
    statuteCitation: string;
    guidanceCitation: string;
    extractedAt: string;
    note: string;
    counts: {
      sections: number;
      rules: number;
      guidanceSections: number;
      guidanceRules: number;
      deferredOutputs: number;
      edges: number;
    };
  };
  groups: { id: string; label: string }[];
  sections: SectionNode[];
  edges: SectionEdge[];
};

// ─── Layout ─────────────────────────────────────────────────────────
// Dagre layered layout, rankdir LR: dependencies on the left, dependents
// on the right, so the bill layer grows out of the sections it touches.

export const CARD_W = 216;
export const CARD_H = 76;

export type XY = { x: number; y: number };

export function layoutPositions(
  ids: string[],
  edges: { from: string; to: string }[],
  opts: { width?: number; height?: number } = {},
): Map<string, XY> {
  const width = opts.width ?? CARD_W;
  const height = opts.height ?? CARD_H;
  const idSet = new Set(ids);

  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 22, ranksep: 90, marginx: 24, marginy: 24 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const id of ids) g.setNode(id, { width, height });
  // Only edges whose endpoints are both present — dagre would otherwise
  // silently materialize phantom nodes for missing endpoints.
  for (const e of edges) {
    if (idSet.has(e.from) && idSet.has(e.to)) g.setEdge(e.from, e.to);
  }
  dagre.layout(g);

  const out = new Map<string, XY>();
  for (const id of ids) {
    const pos = g.node(id);
    if (!pos) continue;
    out.set(id, { x: pos.x - width / 2, y: pos.y - height / 2 });
  }
  return out;
}

// ─── Hover lineage ──────────────────────────────────────────────────
// BFS in both directions from a node; the UI dims everything outside
// the resulting set to keep dense graphs readable.

export type Adjacency = {
  incoming: Map<string, string[]>;
  outgoing: Map<string, string[]>;
};

export function buildAdjacency(
  edges: { from: string; to: string }[],
): Adjacency {
  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();
  for (const e of edges) {
    const inc = incoming.get(e.to);
    if (inc) inc.push(e.from);
    else incoming.set(e.to, [e.from]);
    const out = outgoing.get(e.from);
    if (out) out.push(e.to);
    else outgoing.set(e.from, [e.to]);
  }
  return { incoming, outgoing };
}

export function lineageSet(start: string, adjacency: Adjacency): Set<string> {
  const seen = new Set<string>([start]);
  for (const adj of [adjacency.incoming, adjacency.outgoing]) {
    const queue = [start];
    while (queue.length > 0) {
      const current = queue.shift()!;
      for (const next of adj.get(current) ?? []) {
        if (!seen.has(next)) {
          seen.add(next);
          queue.push(next);
        }
      }
    }
  }
  return seen;
}
