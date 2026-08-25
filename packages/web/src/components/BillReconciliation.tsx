// Reconciliation triage view — the agentic bill ↔ encoding verdicts for
// one bill, as a prioritized queue: filter chips with counts, a ranked
// section listbox, and a detail pane showing both layer verdicts with
// verbatim quotes. Adapted from guidance-impact-visualizer's AnalysisTab;
// the pure ranking lives in ../lib/reconcile/triage.ts.
//
// Data is fetched once by BillPage (shared with the impact graph's
// verdict markers) and passed in; when there are no rows the parent
// hides the whole section, so this component can assume rows.length > 0.

import { useEffect, useMemo, useRef, useState } from "react";
import type { BillReconciliationRow } from "../lib/api";
import type { LayerDiff } from "../lib/reconcile/schema";
import {
  applyFilter,
  diffLabel,
  materialityLabel,
  summarize,
  triage,
  type TriagedTopic,
  type TriageFilter,
} from "../lib/reconcile/triage";
import { fmtDate } from "../lib/format";

export function BillReconciliation({ rows }: { rows: BillReconciliationRow[] }) {
  const [filter, setFilter] = useState<TriageFilter>("all");
  const [selectedSection, setSelectedSection] = useState<string | null>(null);

  const triaged = useMemo(() => triage(rows.map((r) => r.payload)), [rows]);
  const counts = useMemo(() => summarize(triaged), [triaged]);
  const filtered = useMemo(() => applyFilter(triaged, filter), [triaged, filter]);

  const selectedRow =
    triaged.find((r) => r.section === selectedSection) ??
    filtered[0] ??
    triaged[0];

  // Keep the selected list item in view (matters for deep links from the
  // impact graph).
  const itemRefs = useRef(new Map<string, HTMLButtonElement>());
  useEffect(() => {
    if (!selectedRow) return;
    itemRefs.current
      .get(selectedRow.section)
      ?.scrollIntoView({ block: "nearest" });
  }, [selectedRow?.section]);

  const pickFilter = (next: TriageFilter) => {
    setFilter(next);
    const visible = applyFilter(triaged, next);
    if (selectedSection && !visible.some((r) => r.section === selectedSection)) {
      setSelectedSection(visible[0]?.section ?? null);
    }
  };

  // Provenance line: which model produced the verdicts, and when.
  const model = rows.find((r) => r.model)?.model;
  const computedAt = rows
    .map((r) => r.computed_at)
    .filter(Boolean)
    .sort()
    .pop();

  const actionable = filtered.filter((r) => r.hasAction);
  const aligned = filtered.filter((r) => !r.hasAction);

  return (
    <div className="recon">
      <p className="hint recon-intro">
        Each amended section carries two agentic verdicts — the bill against
        current law, and the encoded model against the amended law — ranked
        by how urgently they need attention.
        {model ? (
          <span className="recon-meta">
            {" "}
            {model}
            {computedAt ? ` · ${fmtDate(computedAt)}` : ""}
            {counts.contested > 0
              ? ` · ${counts.contested} contested reading${counts.contested === 1 ? "" : "s"}`
              : ""}
          </span>
        ) : null}
      </p>

      <div
        className="triageFilters"
        role="group"
        aria-label="Filter sections by queue"
      >
        {(
          [
            { id: "all", label: "All sections", count: triaged.length },
            {
              id: "encode-in-model",
              label: "Encode in model",
              count: counts.encode,
              dot: "encode",
            },
            {
              id: "legal-review",
              label: "Legal review",
              count: counts.legal,
              dot: "legal",
            },
            { id: "aligned", label: "Aligned", count: counts.aligned, dot: "clear" },
          ] as { id: TriageFilter; label: string; count: number; dot?: string }[]
        ).map((f) => (
          <button
            key={f.id}
            type="button"
            aria-pressed={filter === f.id}
            className={filter === f.id ? "triageFilter active" : "triageFilter"}
            disabled={f.count === 0}
            onClick={() => pickFilter(f.id)}
          >
            {f.dot ? <span className={`triageFilterDot ${f.dot}`} /> : null}
            {f.label}
            <span className="triageFilterCount">{f.count}</span>
          </button>
        ))}
      </div>

      <div className="triageLayout">
        <div className="triageList" role="listbox" aria-label="Reconciled sections">
          {actionable.map((row) => (
            <TriageListItem
              key={row.section}
              row={row}
              selected={selectedRow?.section === row.section}
              onSelect={() => setSelectedSection(row.section)}
              refMap={itemRefs.current}
            />
          ))}
          {aligned.length > 0 ? (
            <>
              {filter === "all" && actionable.length > 0 ? (
                <p className="triageGroupLabel">Aligned — no action</p>
              ) : null}
              {aligned.map((row) => (
                <TriageListItem
                  key={row.section}
                  row={row}
                  compact
                  selected={selectedRow?.section === row.section}
                  onSelect={() => setSelectedSection(row.section)}
                  refMap={itemRefs.current}
                />
              ))}
            </>
          ) : null}
        </div>

        {selectedRow ? <SectionDetailPane row={selectedRow} /> : null}
      </div>
    </div>
  );
}

// ─── Prioritized list ───────────────────────────────────────────────

function TriageListItem({
  row,
  selected,
  compact = false,
  onSelect,
  refMap,
}: {
  row: TriagedTopic;
  selected: boolean;
  compact?: boolean;
  onSelect: () => void;
  refMap: Map<string, HTMLButtonElement>;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      ref={(el) => {
        if (el) refMap.set(row.section, el);
        else refMap.delete(row.section);
      }}
      className={[
        "triageItem",
        row.worstStatus,
        selected ? "selected" : "",
        compact ? "compact" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onClick={onSelect}
    >
      <span className="triageItemHead">
        <code>{row.section}</code>
        {row.findings.map((finding) => (
          <em key={finding.label} className={`actChip ${finding.action}`}>
            {finding.label}
          </em>
        ))}
        {row.contested ? <em className="contestableTag">contestable</em> : null}
      </span>
      <strong className="triageItemTitle">
        {row.topic.topic.replace(/\s+/g, " ")}
      </strong>
      {!compact ? (
        <span className="triageItemMeta">
          {diffLabel(row.worstStatus)}
          {row.worstMateriality !== "none"
            ? ` · ${materialityLabel(row.worstMateriality)}`
            : ""}
        </span>
      ) : null}
    </button>
  );
}

// ─── Detail pane — everything visible, no toggles ───────────────────

function SectionDetailPane({ row }: { row: TriagedTopic }) {
  return (
    <aside className="triageDetail">
      <div className="triageDetailBody">
        <p className="eyebrow">{row.section}</p>
        <h4 className="triageDetailTitle">
          {row.topic.topic.replace(/\s+/g, " ")}
        </h4>
        {row.findings.length > 0 ? (
          <div className="triageDetailActions">
            {row.findings.map((finding) => (
              <em key={finding.label} className={`actChip ${finding.action}`}>
                {finding.label}
              </em>
            ))}
          </div>
        ) : null}
        <LayerDetail
          label="Bill vs current law"
          upstream="Current law"
          downstream="Bill"
          diff={row.topic.billVsLaw}
        />
        <LayerDetail
          label="Encoded model vs amended law"
          upstream="Amended law"
          downstream="Encoded model"
          diff={row.topic.modelVsLaw}
        />
      </div>
    </aside>
  );
}

function LayerDetail({
  label,
  upstream,
  downstream,
  diff,
}: {
  label: string;
  upstream: string;
  downstream: string;
  diff: LayerDiff;
}) {
  const hasDivergence =
    diff.divergence && diff.divergence.toLowerCase() !== "none";
  return (
    <div className={`layerDetail ${diff.status}`}>
      <div className="layerDetailHead">
        <span className="layerDetailLabel">{label}</span>
        <span className="layerDetailTags">
          <em className={`diffPill ${diff.status}`}>{diffLabel(diff.status)}</em>
          {diff.materiality !== "none" ? (
            <em className={`matChip ${diff.materiality}`}>
              {materialityLabel(diff.materiality)}
            </em>
          ) : null}
          <em className={`confChip ${diff.confidence}`}>
            {diff.confidence} confidence
          </em>
        </span>
      </div>
      {hasDivergence ? (
        <p className="layerDivergence">{diff.divergence}</p>
      ) : (
        <p className="layerDivergence layerAligned">
          Faithfully carried through.
        </p>
      )}
      {diff.rationale ? (
        <p className="layerDetailRationale">{diff.rationale}</p>
      ) : null}
      {diff.ambiguity ? (
        <div className="ambiguityNote">
          <span>Alternative reading</span>
          <p>{diff.ambiguity}</p>
        </div>
      ) : null}
      {diff.upstreamQuote || diff.downstreamQuote ? (
        <div className="layerQuoteGrid">
          {diff.upstreamQuote ? (
            <blockquote className="layerQuote">
              <span>{upstream}</span>“{diff.upstreamQuote}”
            </blockquote>
          ) : null}
          {diff.downstreamQuote ? (
            <blockquote className="layerQuote">
              <span>{downstream}</span>“{diff.downstreamQuote}”
            </blockquote>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
