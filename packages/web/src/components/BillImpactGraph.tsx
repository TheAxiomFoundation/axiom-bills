// Bill impact graph — the encoded model as a section-level dependency
// graph (ReactFlow + dagre), with the bill's touched sections overlaid.
// Ported from guidance-impact-visualizer's ModelGraphTab; the hard-coded
// guidance layer classification is replaced by a client-side join of the
// bill's precomputed diffs (see ../lib/graph/overlay.ts).
//
// Loaded via React.lazy from BillPage: ReactFlow + dagre are the
// heaviest chunk in the app and most bills never show this section.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  api,
  type BillDetail,
  type BillDiffs,
  type BillReconciliationRow,
} from "../lib/api";
import { retry } from "../lib/retry";
import type { TopicDiff } from "../lib/reconcile/schema";
import {
  diffLabel,
  materialityLabel,
  worstMaterialityOf,
  worstStatusOf,
} from "../lib/reconcile/triage";
import {
  buildAdjacency,
  CARD_H,
  CARD_W,
  layoutPositions,
  lineageSet,
  type RulespecGraph,
  type RuleSummary,
  type SectionEdge,
  type SectionNode as SectionData,
} from "../lib/graph/rulespec-graph";
import {
  billOverlay,
  focusOnBill,
  splitRulesByBillImpact,
} from "../lib/graph/overlay";

// "focus" trims the overlay to the bill's neighborhood — monorepo
// snapshots run to hundreds of sections and the full canvas is
// unreadable at that scale. "overlay" keeps the whole repo visible.
type ViewMode = "baseline" | "overlay" | "focus";

// ─── Node rendering ─────────────────────────────────────────────────

type SectionFlowData = {
  section: SectionData;
  groupLabel: string;
  contested: boolean;
  isSelected: boolean;
  [key: string]: unknown;
};

function SectionCardNode({ data }: NodeProps) {
  const { section, groupLabel, contested, isSelected } =
    data as SectionFlowData;
  return (
    <div
      className={[
        "rsNode",
        `rsNode-${section.layer}`,
        isSelected ? "rsNode-selected" : "",
      ].join(" ")}
    >
      <Handle type="target" position={Position.Left} className="rsHandle" />
      <Handle type="source" position={Position.Right} className="rsHandle" />
      <div className="rsNodeHead">
        <code>{section.id}</code>
        {contested ? (
          <span className="rsContested" title="Contested reading">
            ✳
          </span>
        ) : null}
        {section.deferred.length > 0 ? (
          <span className="rsGap">
            {section.deferred.length} gap{section.deferred.length > 1 ? "s" : ""}
          </span>
        ) : null}
      </div>
      <p className="rsNodeLabel">{section.label}</p>
      <p className="rsNodeMeta">
        {section.layer === "statute"
          ? "this bill"
          : section.layer === "placeholder"
          ? "not yet encoded"
          : `${section.ruleCount} rule${section.ruleCount === 1 ? "" : "s"} · ${groupLabel}`}
      </p>
    </div>
  );
}

const nodeTypes = { section: SectionCardNode };

// ─── Component ──────────────────────────────────────────────────────

export default function BillImpactGraph({
  bill,
  diffs,
  reconciliations,
}: {
  bill: BillDetail;
  diffs: BillDiffs;
  // Agentic verdicts, fetched once by BillPage and shared with the
  // reconciliation triage section. Optional: markers simply don't render
  // until (or unless) verdicts exist.
  reconciliations?: BillReconciliationRow[];
}) {
  // The repo whose graph we show: the one the bill's matched encodings
  // live in. Falls back to the jurisdiction's conventional repo name so
  // needs_new_encoding-only bills (no matched rule file) still resolve.
  const repo = useMemo(() => {
    for (const sec of diffs.sections) {
      if (sec.encoding) return sec.encoding.repo;
    }
    return bill.matched_encodings[0]?.repo ?? `rulespec-${bill.jurisdiction}`;
  }, [diffs, bill]);

  const [graph, setGraph] = useState<RulespecGraph | null>(null);
  const [fetchState, setFetchState] =
    useState<"loading" | "ready" | "missing" | "error">("loading");

  useEffect(() => {
    let cancelled = false;
    setFetchState("loading");
    setGraph(null);
    retry(() => api.encodingGraph(repo))
      .then((g) => {
        if (cancelled) return;
        setGraph(g);
        setFetchState(g ? "ready" : "missing");
      })
      .catch(() => {
        if (!cancelled) setFetchState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [repo]);

  if (fetchState === "loading") {
    return <p className="hint">Loading the encoding graph…</p>;
  }
  if (fetchState === "error") {
    return <p className="error">Couldn’t load the encoding graph.</p>;
  }
  if (fetchState === "missing" || !graph) {
    return (
      <p className="hint">
        No dependency graph has been generated for <code>{repo}</code> yet.
      </p>
    );
  }
  return (
    <GraphView
      graph={graph}
      bill={bill}
      diffs={diffs}
      reconciliations={reconciliations ?? []}
    />
  );
}

const norm = (s: string) => s.trim().toLowerCase();

function GraphView({
  graph,
  bill,
  diffs,
  reconciliations,
}: {
  graph: RulespecGraph;
  bill: BillDetail;
  diffs: BillDiffs;
  reconciliations: BillReconciliationRow[];
}) {
  const [mode, setMode] = useState<ViewMode>("focus");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  const overlay = useMemo(
    () => billOverlay(graph, diffs, bill),
    [graph, diffs, bill],
  );
  const focused = useMemo(() => focusOnBill(overlay), [overlay]);

  // Reconciliation verdicts keyed by every citation form we might meet:
  // the row's section_citation and the payload's target citation. Graph
  // nodes join on their own id/legalId or, for touched sections, on the
  // diff citation the overlay recorded for them.
  const verdictByCitation = useMemo(() => {
    const m = new Map<string, TopicDiff>();
    for (const r of reconciliations) {
      m.set(norm(r.section_citation), r.payload);
      if (r.payload.section) m.set(norm(r.payload.section), r.payload);
    }
    return m;
  }, [reconciliations]);

  const verdictForNode = useMemo(() => {
    return (id: string): TopicDiff | null => {
      if (verdictByCitation.size === 0) return null;
      const section = graph.sections.find((s) => s.id === id);
      const candidates = [
        id,
        section?.legalId,
        overlay.diffCitationById[id],
      ];
      for (const c of candidates) {
        const v = c ? verdictByCitation.get(norm(c)) : undefined;
        if (v) return v;
      }
      return null;
    };
  }, [verdictByCitation, graph, overlay]);

  // Baseline mode = the stored graph as-is; overlay mode adds the bill
  // node, relabelled touched sections, and backlog placeholders.
  const activeView =
    mode === "focus" ? focused : mode === "overlay" ? overlay : null;
  const activeSections: SectionData[] = activeView
    ? activeView.sections
    : graph.sections;
  const activeEdges: SectionEdge[] = activeView
    ? activeView.edges
    : graph.edges;

  const sectionsById = useMemo(
    () => new Map(activeSections.map((s) => [s.id, s])),
    [activeSections],
  );
  const groupLabel = useMemo(
    () => new Map(graph.groups.map((g) => [g.id, g.label])),
    [graph],
  );

  const { nodes, edges } = useMemo(() => {
    const activeIds = new Set(activeSections.map((s) => s.id));

    const flowEdges: Edge[] = activeEdges
      .filter((e) => activeIds.has(e.from) && activeIds.has(e.to))
      .map((e) => {
        const touchesBill =
          sectionsById.get(e.from)!.layer !== "baseline" ||
          sectionsById.get(e.to)!.layer !== "baseline";
        // The synthetic bill edges get a verb so the graph explains
        // itself: "amends" into an existing encoding, "adds" into a
        // not-yet-encoded placeholder.
        const label =
          e.type === "implements"
            ? sectionsById.get(e.to)!.layer === "placeholder"
              ? "adds"
              : "amends"
            : undefined;
        return {
          id: `${e.from}->${e.to}`,
          source: e.from,
          target: e.to,
          type: "smoothstep",
          className: touchesBill ? "rsEdge-bill" : "rsEdge-baseline",
          animated: e.type === "implements",
          label,
          labelStyle: { fontSize: 10, fill: "var(--color-ink-muted)" },
          labelBgStyle: { fill: "var(--color-paper)", fillOpacity: 0.85 },
          style: e.type === "reference" ? { strokeDasharray: "6 4" } : undefined,
          markerEnd: { type: MarkerType.ArrowClosed, width: 13, height: 13 },
        };
      });

    const positions = layoutPositions(
      activeSections.map((s) => s.id),
      activeEdges,
    );

    const flowNodes: Node[] = activeSections.map((section) => {
      const verdict = mode !== "baseline" ? verdictForNode(section.id) : null;
      return {
        id: section.id,
        type: "section",
        position: positions.get(section.id) ?? { x: 0, y: 0 },
        // Explicit dimensions: React Flow skips its measure pass, so
        // hover-driven re-renders never flash unmeasured nodes.
        width: CARD_W,
        height: CARD_H,
        draggable: true,
        data: {
          section,
          groupLabel:
            section.group === "bill"
              ? bill.number
              : groupLabel.get(section.group) ?? section.group,
          contested: Boolean(
            verdict &&
              (verdict.billVsLaw.ambiguity || verdict.modelVsLaw.ambiguity),
          ),
          isSelected: selectedId === section.id,
        } satisfies SectionFlowData,
      };
    });

    return { nodes: flowNodes, edges: flowEdges };
  }, [
    activeSections,
    activeEdges,
    selectedId,
    sectionsById,
    groupLabel,
    bill,
    mode,
    verdictForNode,
  ]);

  // Hover lineage: BFS both directions from the hovered node, dim the
  // rest — keeps dense graphs readable.
  const adjacency = useMemo(
    () =>
      buildAdjacency(
        edges.map((e) => ({ from: e.source, to: e.target })),
      ),
    [edges],
  );

  const highlightSet = useMemo(() => {
    if (!hoveredId) return null;
    return lineageSet(hoveredId, adjacency);
  }, [hoveredId, adjacency]);

  const displayNodes = useMemo(() => {
    if (!highlightSet) return nodes;
    return nodes.map((n) => ({
      ...n,
      className: highlightSet.has(n.id) ? "rsOnPath" : "rsDimmed",
    }));
  }, [nodes, highlightSet]);

  const displayEdges = useMemo(() => {
    if (!highlightSet) return edges;
    return edges.map((e) => {
      const lit = highlightSet.has(e.source) && highlightSet.has(e.target);
      return {
        ...e,
        className: `${e.className ?? ""} ${lit ? "rsOnPath" : "rsDimmed"}`.trim(),
      };
    });
  }, [edges, highlightSet]);

  const toggleFullscreen = useCallback(() => {
    if (!wrapRef.current) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void wrapRef.current.requestFullscreen();
  }, []);

  useEffect(() => {
    const handler = () =>
      setIsFullscreen(document.fullscreenElement === wrapRef.current);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  const selected = selectedId ? sectionsById.get(selectedId) ?? null : null;
  const touchedCount = overlay.sections.filter((s) => s.layer === "bill").length;
  const backlogCount = overlay.sections.filter(
    (s) => s.layer === "placeholder",
  ).length;

  return (
    <div className="impact-graph">
      <div className="impact-graph-head">
        <div className="impact-graph-intro">
          <p className="hint">
            Each card is one encoded rule file from{" "}
            <code>{graph.meta.generatedFrom || "rulespec"}</code>; arrows show
            which files' rules feed into which.
            {mode !== "baseline" && overlay.billNodeId
              ? ` The dark card is ${bill.number} itself — an "amends" arrow
                 points at each encoded file it changes (${touchedCount})` +
                (backlogCount > 0
                  ? `, and an "adds" arrow at each dashed placeholder for a
                     provision it creates that has no encoding yet (${backlogCount}).`
                  : ".")
              : ""}{" "}
            Hover a card to trace everything upstream and downstream of it;
            click it for its rules.
          </p>
        </div>
        <div className="filters" role="tablist" aria-label="Graph view">
          <button
            type="button"
            className={mode === "baseline" ? "on" : ""}
            onClick={() => {
              setMode("baseline");
              setSelectedId(null);
            }}
          >
            Baseline
          </button>
          <button
            type="button"
            className={
              mode === "overlay" || (mode === "focus" && !overlay.billNodeId)
                ? "on"
                : ""
            }
            onClick={() => setMode("overlay")}
          >
            Full graph
          </button>
          {overlay.billNodeId ? (
            <button
              type="button"
              className={mode === "focus" ? "on" : ""}
              onClick={() => setMode("focus")}
            >
              With {bill.number}
            </button>
          ) : null}
        </div>
      </div>

      <div className="impact-layout">
        <div className="impact-canvas-wrap">
          <div
            ref={wrapRef}
            className={`impact-canvas ${isFullscreen ? "impact-canvas--fullscreen" : ""}`}
          >
            <ReactFlowProvider>
              <ReactFlow
                key={mode}
                nodes={displayNodes}
                edges={displayEdges}
                nodeTypes={nodeTypes}
                fitView
                fitViewOptions={{ padding: 0.15, minZoom: 0.3, maxZoom: 1.2 }}
                minZoom={0.2}
                maxZoom={2}
                nodesDraggable
                nodesConnectable={false}
                elementsSelectable
                proOptions={{ hideAttribution: true }}
                onNodeMouseEnter={(_, node) => setHoveredId(node.id)}
                onNodeMouseLeave={() => setHoveredId(null)}
                onNodeClick={(_, node) => setSelectedId(node.id)}
                onPaneClick={() => setSelectedId(null)}
              >
                <Background
                  variant={BackgroundVariant.Dots}
                  gap={18}
                  size={1}
                  color="var(--color-rule)"
                />
                <MiniMap
                  nodeColor={(n) => {
                    const layer = (n.data as SectionFlowData).section?.layer;
                    return layer === "bill"
                      ? "#fbbf24"
                      : layer === "statute"
                        ? "#1c1917"
                        : layer === "placeholder"
                          ? "#faf9f6"
                          : "#e7e5e4";
                  }}
                  nodeBorderRadius={2}
                  pannable
                  zoomable
                  position="bottom-right"
                />
                <Controls position="bottom-left" showInteractive={false} />
              </ReactFlow>
              <button
                type="button"
                className="impact-fullscreen-btn"
                onClick={toggleFullscreen}
                title={isFullscreen ? "Exit full screen (Esc)" : "Full screen"}
                aria-label={isFullscreen ? "Exit full screen" : "Full screen"}
              >
                {isFullscreen ? (
                  <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden>
                    <path
                      d="M6 2v4H2M10 2v4h4M6 14v-4H2M10 14v-4h4"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      fill="none"
                      strokeLinecap="round"
                    />
                  </svg>
                ) : (
                  <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden>
                    <path
                      d="M2 6V2h4M14 6V2h-4M2 10v4h4M14 10v4h-4"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      fill="none"
                      strokeLinecap="round"
                    />
                  </svg>
                )}
              </button>
            </ReactFlowProvider>
          </div>
          <ul className="impact-legend">
            <li>
              <span className="impact-swatch impact-swatch--baseline" /> Encoded model
            </li>
            <li>
              <span className="impact-swatch impact-swatch--bill" /> Touched by this bill
            </li>
            <li>
              <span className="impact-swatch impact-swatch--statute" /> The bill
            </li>
            <li>
              <span className="impact-swatch impact-swatch--placeholder" /> Not yet encoded
            </li>
            <li>
              <span className="impact-swatch impact-swatch--gap" /> Deferred outputs (gaps)
            </li>
            <li>
              <span className="impact-edge impact-edge--dashed" /> Formula reference
            </li>
            <li>
              <span className="impact-edge" /> Import
            </li>
            {reconciliations.length > 0 ? (
              <li>
                <span className="impact-legend-mark">✳</span> Contested reading
              </li>
            ) : null}
          </ul>
        </div>

        <aside className="impact-detail">
          {selected ? (
            <SectionDetail
              section={selected}
              groupLabel={
                selected.group === "bill"
                  ? bill.number
                  : groupLabel.get(selected.group) ?? selected.group
              }
              diffCitation={overlay.diffCitationById[selected.id] ?? null}
              amendedCitations={
                mode !== "baseline"
                  ? overlay.diffCitationsById[selected.id] ?? []
                  : []
              }
              edges={activeEdges}
              sectionsById={sectionsById}
              onSelect={setSelectedId}
              verdict={mode !== "baseline" ? verdictForNode(selected.id) : null}
              mode={mode}
            />
          ) : (
            <div className="impact-detail-empty">
              <p>
                Select a section to see its RuleSpec rules and deferred
                outputs.
              </p>
              <p className="impact-detail-hint">
                Amber sections are the ones this bill amends. A “gaps” badge
                means the encoding defers an output — acknowledged but not
                yet executable. Dashed nodes are amended provisions with no
                encoding yet.
              </p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

// ─── Detail pane ────────────────────────────────────────────────────

function layerDescription(section: SectionData): string {
  switch (section.layer) {
    case "statute":
      return "This bill";
    case "bill":
      return "Amended by this bill";
    case "placeholder":
      return "Encoder backlog";
    default:
      return "Encoded model";
  }
}

function SectionDetail({
  section,
  groupLabel,
  diffCitation,
  amendedCitations,
  edges,
  sectionsById,
  onSelect,
  verdict,
  mode,
}: {
  section: SectionData;
  groupLabel: string;
  diffCitation: string | null;
  amendedCitations: string[];
  edges: SectionEdge[];
  sectionsById: Map<string, SectionData>;
  onSelect: (id: string) => void;
  verdict: TopicDiff | null;
  mode: ViewMode;
}) {
  const worstStatus = verdict
    ? worstStatusOf(verdict.billVsLaw.status, verdict.modelVsLaw.status)
    : null;
  const worstMateriality = verdict
    ? worstMaterialityOf(
        verdict.billVsLaw.materiality,
        verdict.modelVsLaw.materiality,
      )
    : null;

  // Rule-level impact: which of this FILE's rules does the bill
  // directly invalidate (source citation intersects an amended
  // subsection), vs. the rest of the file.
  const { direct, other } = splitRulesByBillImpact(
    section.rules,
    amendedCitations,
  );
  const directNames = new Set(direct.map((r) => r.name));

  // Neighbors, split by direction. Edges run dependency → consumer, so
  // edges INTO this node are what it depends on, and edges OUT of it
  // are its upstream consumers — the sections whose encodings would be
  // indirectly affected if this one changes. `via` names the imported
  // rule, letting us mark consumers of the directly amended code.
  const dependsOn = edges.filter(
    (e) => e.to === section.id && e.type !== "implements",
  );
  const consumers = edges.filter(
    (e) => e.from === section.id && e.type !== "implements",
  );
  return (
    <div className="impact-detail-body">
      <p className="impact-detail-eyebrow">
        {layerDescription(section)} · {groupLabel}
      </p>
      <h4 className="impact-detail-title">{section.label}</h4>
      <code className="impact-detail-code">{section.legalId}</code>
      {section.summary ? (
        <p className="impact-detail-summary">{section.summary}</p>
      ) : null}

      {verdict && worstStatus ? (
        <p className="impact-verdict">
          <em className={`diffPill ${worstStatus}`}>{diffLabel(worstStatus)}</em>
          {worstMateriality && worstMateriality !== "none" ? (
            <em className={`matChip ${worstMateriality}`}>
              {materialityLabel(worstMateriality)}
            </em>
          ) : null}
          {verdict.billVsLaw.ambiguity || verdict.modelVsLaw.ambiguity ? (
            <em className="contestableTag">contestable</em>
          ) : null}
          <a href="#bill-reconciliation">View in reconciliation ↓</a>
        </p>
      ) : null}

      {mode !== "baseline" && diffCitation && section.layer !== "statute" ? (
        <p className="impact-detail-link">
          <a href="#bill-diffs">
            {section.layer === "placeholder"
              ? "View the new provision in the section-by-section diff ↓"
              : `View the diff for ${diffCitation} ↓`}
          </a>
        </p>
      ) : null}

      {section.deferred.length > 0 ? (
        <div className="impact-detail-block">
          <p className="impact-detail-block-title">
            Deferred outputs · decisions needed
          </p>
          {section.deferred.map((gap) => (
            <div className="impact-gap-card" key={gap.output}>
              <code>{gap.output}</code>
              <p>{gap.reason}</p>
            </div>
          ))}
        </div>
      ) : null}

      {direct.length > 0 ? (
        <div className="impact-detail-block">
          <p className="impact-detail-block-title impact-detail-block-title--direct">
            Directly amended by this bill ({direct.length})
          </p>
          <p className="impact-detail-hint">
            Rules whose source citation covers{" "}
            {amendedCitations.map((c, i) => (
              <span key={c}>
                {i > 0 ? ", " : ""}
                <code>{c}</code>
              </span>
            ))}
            — this is the encoded logic the amendment invalidates.
          </p>
          <RuleList rules={direct} direct />
        </div>
      ) : null}

      {other.length > 0 ? (
        <div className="impact-detail-block">
          <p className="impact-detail-block-title">
            {direct.length > 0
              ? `Other rules in this file (${other.length})`
              : `Rules (${section.ruleCount})`}
          </p>
          <RuleList rules={other} />
        </div>
      ) : null}

      {consumers.length > 0 ? (
        <div className="impact-detail-block">
          <p className="impact-detail-block-title">
            Used by · upstream consumers ({consumers.length})
          </p>
          <ul className="impact-neighbor-list">
            {consumers.map((e) => {
              const importsAmended = Boolean(e.via && directNames.has(e.via));
              return (
                <li key={`${e.from}->${e.to}`}>
                  <button type="button" onClick={() => onSelect(e.to)}>
                    <code>{e.to}</code>
                    <span className="impact-neighbor-label">
                      {sectionsById.get(e.to)?.label ?? ""}
                    </span>
                  </button>
                  {e.via ? (
                    <span
                      className={
                        importsAmended
                          ? "impact-via impact-via--amended"
                          : "impact-via"
                      }
                    >
                      imports <code>{e.via}</code>
                      {importsAmended ? " — amended above" : ""}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {dependsOn.length > 0 ? (
        <div className="impact-detail-block">
          <p className="impact-detail-block-title">
            Depends on ({dependsOn.length})
          </p>
          <ul className="impact-neighbor-list">
            {dependsOn.map((e) => (
              <li key={`${e.from}->${e.to}`}>
                <button type="button" onClick={() => onSelect(e.from)}>
                  <code>{e.from}</code>
                  <span className="impact-neighbor-label">
                    {sectionsById.get(e.from)?.label ?? ""}
                  </span>
                </button>
                {e.via ? (
                  <span className="impact-via">
                    provides <code>{e.via}</code>
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function RuleList({
  rules,
  direct = false,
}: {
  rules: RuleSummary[];
  direct?: boolean;
}) {
  return (
    <ul className="impact-rule-list">
      {rules.map((rule) => (
        <li key={rule.name} className={direct ? "impact-rule--direct" : ""}>
          <code>{rule.name}</code>
          <span className="impact-rule-meta">
            <em className={`impact-rule-kind impact-rule-kind--${rule.kind}`}>
              {rule.kind}
            </em>
            {rule.source ? (
              <span className="impact-rule-source">{rule.source}</span>
            ) : null}
          </span>
        </li>
      ))}
    </ul>
  );
}
