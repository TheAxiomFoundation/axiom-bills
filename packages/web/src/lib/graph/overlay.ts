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
import { buildAdjacency, lineageSet } from "./rulespec-graph";
import type {
  RulespecGraph,
  RuleSummary,
  SectionEdge,
  SectionNode,
} from "./rulespec-graph";

export type BillForOverlay = {
  number: string;
  title?: string | null;
};

export type OverlayResult = {
  sections: SectionNode[];
  edges: SectionEdge[];
  /** Graph-node id → first bill diff-section citation, for deep links
   *  into the section-by-section diff view. */
  diffCitationById: Record<string, string>;
  /** Graph-node id → ALL diff-section citations that touched it. A bill
   *  can amend several subsections of one encoded file (each its own
   *  diff section); rule-level impact needs every one of them. */
  diffCitationsById: Record<string, string[]>;
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

  // Node id → the diff section citations that touched it (first one is
  // the deep-link target; the full list drives rule-level impact).
  const touched = new Map<string, string>();
  const touchedAll = new Map<string, string[]>();
  const recordTouch = (nodeId: string, citation: string) => {
    if (!touched.has(nodeId)) touched.set(nodeId, citation);
    const all = touchedAll.get(nodeId);
    if (!all) touchedAll.set(nodeId, [citation]);
    else if (!all.includes(citation)) all.push(citation);
  };
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
          recordTouch(node.id, sec.citation);
          break;
        }
      }
    } else if (sec.encoding_backlog) {
      const key = norm(sec.citation);
      // Snapshot-skew guard: diffs and the graph come from separate
      // hourly jobs, so a citation flagged as backlog may already exist
      // in a fresher graph snapshot. Treat it as a touched section
      // instead of pushing a duplicate node id.
      const node = byCitation.get(key);
      if (node) {
        recordTouch(node.id, sec.citation);
      } else if (!backlogSeen.has(key)) {
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
  const diffCitationsById: Record<string, string[]> = {};
  for (const [id, cites] of touchedAll) diffCitationsById[id] = cites;

  if (touched.size === 0 && backlog.length === 0) {
    return { sections, edges, diffCitationById, diffCitationsById, billNodeId: null };
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
    diffCitationsById[b.citation] = [b.citation];
  }

  return { sections, edges, diffCitationById, diffCitationsById, billNodeId };
}

// ─── Rule-level impact ──────────────────────────────────────────────
// A touched node is a whole rulespec FILE; the bill usually amends one
// subsection of it. Rules carry per-subsection `source` citations, so
// we can split the file's rules into the code the bill DIRECTLY
// invalidates vs. the rest — and the graph's `via` edge labels then
// separate upstream consumers of the amended rules from everything else.

const normCite = (s: string) => s.trim().toLowerCase().replace(/\s+/g, " ");

/** Do two legal citations cover overlapping text? True when equal, or
 *  when one addresses a subdivision of the other — "26 USC 25E" covers
 *  "26 USC 25E(g)"; "7 CFR 273.3" covers "7 CFR 273.3(a)". Sibling
 *  subdivisions ("25E(a)" vs "25E(g)") do not intersect. */
export function citationsIntersect(a: string, b: string): boolean {
  const x = normCite(a);
  const y = normCite(b);
  if (!x || !y) return false;
  return (
    x === y ||
    x.startsWith(`${y}(`) ||
    y.startsWith(`${x}(`) ||
    x.startsWith(`${y}.`) ||
    y.startsWith(`${x}.`)
  );
}

/** Split a section's rules into those whose source citations intersect
 *  any of the bill's amended citations for this node (directly
 *  invalidated code) and the rest of the file. Rules with no source at
 *  all are kept in `other` — no evidence either way. */
export function splitRulesByBillImpact(
  rules: RuleSummary[],
  amendedCitations: string[],
): { direct: RuleSummary[]; other: RuleSummary[] } {
  const direct: RuleSummary[] = [];
  const other: RuleSummary[] = [];
  for (const rule of rules) {
    const sources = (rule.source ?? "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const hit = sources.some((src) =>
      amendedCitations.some((cite) => citationsIntersect(src, cite)),
    );
    (hit ? direct : other).push(rule);
  }
  return { direct, other };
}

// The Medicaid-scale reference app rendered whole-program graphs of a
// few dozen sections; a rulespec monorepo snapshot has hundreds, most
// of them unrelated to any one bill. Focus the graph on the bill's
// neighborhood: the touched/placeholder/bill nodes plus the full
// dependency lineage of each touched section, and only edges between
// surviving nodes. Returns the input unchanged when nothing is touched
// (no bill node means there is nothing to focus on).
export function focusOnBill(overlay: OverlayResult): OverlayResult {
  if (!overlay.billNodeId) return overlay;
  const adjacency = buildAdjacency(overlay.edges);
  const keep = new Set<string>();
  for (const s of overlay.sections) {
    if (s.layer !== "baseline") keep.add(s.id);
  }
  for (const s of overlay.sections) {
    if (s.layer === "bill") {
      for (const id of lineageSet(s.id, adjacency)) keep.add(id);
    }
  }
  return {
    ...overlay,
    sections: overlay.sections.filter((s) => keep.has(s.id)),
    edges: overlay.edges.filter((e) => keep.has(e.from) && keep.has(e.to)),
  };
}
