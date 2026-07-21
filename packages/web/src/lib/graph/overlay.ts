// Client-side join of a bill's precomputed diffs onto the rulespec
// section graph. Replaces the visualizer's hard-coded layer
// classification: stored sections are all layer "baseline"; here we
//
//   - relabel sections the bill amends as layer "bill";
//   - add one synthetic node for the bill itself (layer "statute",
//     the near-black anchor card) with `implements` edges into each
//     touched section;
//   - add dashed "placeholder" nodes for needs_new_encoding backlog
//     citations — amendments in an encoded program area that no
//     existing rule file covers.
//
// Pure functions only (no React, no fetching) so this is unit-testable.

import type { BillDiffs } from "../api";
import type { RulespecGraph, SectionEdge, SectionNode } from "./rulespec-graph";

export type BillForOverlay = {
  number: string;
  title?: string | null;
};

export type OverlayResult = {
  sections: SectionNode[];
  edges: SectionEdge[];
  /** Graph-node id → bill diff-section citation, for deep links into
   *  the section-by-section diff view. */
  diffCitationById: Record<string, string>;
  /** Id of the synthetic bill node, or null when the bill touches
   *  nothing in this graph. */
  billNodeId: string | null;
};

// TS port of the scrapers' parse_citation_from_path — a rulespec file's
// path is its citation address:
//   statutes/26/32/a/1.yaml      → "26 USC 32(a)(1)"
//   regulations/7-cfr/273/3.yaml → "7 CFR 273.3"
//   policies/usda/snap/x.yaml    → "policy:usda/snap/x"
export function citationFromFilePath(filePath: string): string | null {
  if (!filePath.endsWith(".yaml")) return null;
  const parts = filePath.slice(0, -".yaml".length).split("/").filter(Boolean);
  if (parts.length < 2) return null;
  const [root, ...rest] = parts;

  if (root === "statutes") {
    const [title, section, ...subs] = rest;
    if (!title || !/^\d+$/.test(title)) return null;
    if (!section) return `${title} USC`;
    return `${title} USC ${section}${subs.map((s) => `(${s})`).join("")}`;
  }
  if (root === "regulations") {
    const [titleCfr, partNo, section, ...subs] = rest;
    if (!titleCfr || !titleCfr.endsWith("-cfr")) return null;
    const title = titleCfr.slice(0, -"-cfr".length);
    if (!/^\d+$/.test(title) || !partNo || !section) return null;
    return `${title} CFR ${partNo}.${section}${subs.map((s) => `(${s})`).join("")}`;
  }
  if (root === "policies") {
    return `policy:${rest.join("/")}`;
  }
  return null;
}

const norm = (s: string) => s.trim().toLowerCase();

export function billOverlay(
  graph: RulespecGraph,
  diffs: BillDiffs,
  bill: BillForOverlay,
): OverlayResult {
  // Index graph nodes by both id and legalId — generators differ on
  // whether id is the short form ("435.552") or the full citation.
  const byCitation = new Map<string, SectionNode>();
  for (const s of graph.sections) {
    byCitation.set(norm(s.id), s);
    if (s.legalId) byCitation.set(norm(s.legalId), s);
  }

  // Node id → the diff section citation that touched it.
  const touched = new Map<string, string>();
  // Backlog citations (encoding_backlog, no matched rule file).
  const backlog: { citation: string; heading: string | null }[] = [];
  const backlogSeen = new Set<string>();

  for (const sec of diffs.sections) {
    if (sec.encoding) {
      const candidates = [
        sec.encoding.citation,
        citationFromFilePath(sec.encoding.file_path),
      ];
      for (const c of candidates) {
        const node = c ? byCitation.get(norm(c)) : undefined;
        if (node) {
          if (!touched.has(node.id)) touched.set(node.id, sec.citation);
          break;
        }
      }
    } else if (sec.encoding_backlog) {
      const key = norm(sec.citation);
      if (!backlogSeen.has(key)) {
        backlogSeen.add(key);
        backlog.push({ citation: sec.citation, heading: sec.heading });
      }
    }
  }

  const sections: SectionNode[] = graph.sections.map((s) =>
    touched.has(s.id) ? { ...s, layer: "bill" as const } : s,
  );
  const edges: SectionEdge[] = [...graph.edges];
  const diffCitationById: Record<string, string> = {};
  for (const [id, cite] of touched) diffCitationById[id] = cite;

  if (touched.size === 0 && backlog.length === 0) {
    return { sections, edges, diffCitationById, billNodeId: null };
  }

  const billNodeId = bill.number;
  sections.push({
    id: billNodeId,
    legalId: billNodeId,
    label: bill.title?.trim() || bill.number,
    group: "bill",
    layer: "statute",
    summary:
      "The bill under review. Solid edges point at the encoded sections " +
      "its amendments touch; dashed placeholder nodes are amended " +
      "provisions not yet encoded.",
    ruleCount: 0,
    rules: [],
    deferred: [],
  });

  for (const id of touched.keys()) {
    edges.push({ from: billNodeId, to: id, type: "implements" });
  }

  for (const b of backlog) {
    sections.push({
      id: b.citation,
      legalId: b.citation,
      label: b.heading?.trim() || "Not yet encoded",
      group: "bill",
      layer: "placeholder",
      summary:
        "New provision in an encoded program area. No existing rule file " +
        "covers this amendment — on enactment it goes to the encoder backlog.",
      ruleCount: 0,
      rules: [],
      deferred: [],
    });
    edges.push({ from: billNodeId, to: b.citation, type: "implements" });
    diffCitationById[b.citation] = b.citation;
  }

  return { sections, edges, diffCitationById, billNodeId };
}
