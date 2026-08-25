// Types for the agentic bill ↔ encoding reconciliation layer.
//
// Ported from guidance-impact-visualizer's src/lib/diff/schema.ts. The two
// compared layers are renamed for the bills context:
//
//   billVsLaw  — Δ1: the bill's amendment vs the current-law provision
//   modelVsLaw — Δ2: the encoded RuleSpec model vs the amended law
//
// These shapes are shared with the scrapers' `reconcile` pipeline, which
// writes one row per (bill, section) into bills.bill_reconciliations with
// the verdict pair as the `payload` JSONB.

export type DiffStatus =
  | "aligned" // faithfully carried through
  | "adds-detail" // downstream adds detail the upstream layer left open
  | "narrows" // downstream is stricter / narrower than upstream
  | "conflicts" // downstream contradicts upstream
  | "missing"; // upstream requirement not reflected downstream

export type Confidence = "high" | "medium" | "low";

// Does the divergence actually matter, and to whom?
export type Materiality =
  | "changes-eligibility" // alters who is an applicable/eligible/excluded individual
  | "changes-state-duty" // alters what a State must or may do
  | "procedural" // process/notice/verification mechanics only
  | "cosmetic" // wording/structure/ordering, no legal effect
  | "none"; // aligned / nothing diverges

// Where the finding should be routed.
export type DiffAction =
  | "encode-in-model" // a real requirement is absent/wrong in the encoded model
  | "legal-review" // raises a question of legal authority/meaning for a lawyer
  | "none";

export type LayerDiff = {
  status: DiffStatus;
  divergence: string; // the single element that differs (≤25 words), or "none"
  materiality: Materiality;
  action: DiffAction;
  confidence: Confidence; // how settled the reading is
  rationale: string; // ≤1 sentence justifying the call
  // Where the interpretation is contestable, and the plausible alternative
  // reading. Omitted when the call is straightforward.
  ambiguity?: string;
  upstreamQuote?: string; // verbatim from the higher-authority layer
  downstreamQuote?: string; // verbatim from the lower layer
};

export type TopicDiff = {
  topic: string; // e.g. "Monthly activity threshold"
  section: string; // the target citation, e.g. "42 USC 1396a(xx)"
  // Δ1: the bill's amendment vs the current-law provision
  billVsLaw: LayerDiff;
  // Δ2: the encoded RuleSpec model vs the amended law
  modelVsLaw: LayerDiff;
};

export type ReconLayer = "billVsLaw" | "modelVsLaw";

// Window event the impact graph's "View in reconciliation ↓" anchor
// dispatches on click. BillPage's reconciliation section listens for it
// and opens itself — hashchange alone misses the case where the hash is
// already #bill-reconciliation (navigating to the same fragment fires
// no event).
export const OPEN_RECONCILIATION_EVENT = "axiom-bills:open-reconciliation";

// ─── Payload validation ─────────────────────────────────────────────
// Runtime vocabularies for the enums above. The payload JSONB is written
// by an LLM pipeline, so api.billReconciliations validates every layer
// at the fetch boundary — one out-of-vocabulary token must not yield
// NaN triage scores or leak raw strings into classNames and labels.

export const DIFF_STATUSES: readonly DiffStatus[] = [
  "aligned", "adds-detail", "narrows", "conflicts", "missing",
];

export const CONFIDENCES: readonly Confidence[] = ["high", "medium", "low"];

export const MATERIALITIES: readonly Materiality[] = [
  "changes-eligibility", "changes-state-duty", "procedural", "cosmetic", "none",
];

export const DIFF_ACTIONS: readonly DiffAction[] = [
  "encode-in-model", "legal-review", "none",
];

function oneOf<T extends string>(vocab: readonly T[], v: unknown): v is T {
  return typeof v === "string" && (vocab as readonly string[]).includes(v);
}

/** Validate one payload layer. Returns null when the layer is missing or
 * its status is out of vocabulary — status is the core verdict and has
 * no safe substitute, so the row is dropped like a missing layer. The
 * softer enums are coerced to their semantically-safest member instead:
 * materiality → "none" (renders no chip), action → "legal-review"
 * (routes a garbled verdict to a human rather than hiding it),
 * confidence → "low". */
export function sanitizeLayerDiff(raw: unknown): LayerDiff | null {
  if (!raw || typeof raw !== "object") return null;
  const d = raw as Record<string, unknown>;
  if (!oneOf(DIFF_STATUSES, d.status)) return null;
  return {
    status: d.status,
    divergence: typeof d.divergence === "string" ? d.divergence : "",
    materiality: oneOf(MATERIALITIES, d.materiality) ? d.materiality : "none",
    action: oneOf(DIFF_ACTIONS, d.action) ? d.action : "legal-review",
    confidence: oneOf(CONFIDENCES, d.confidence) ? d.confidence : "low",
    rationale: typeof d.rationale === "string" ? d.rationale : "",
    ...(typeof d.ambiguity === "string" && d.ambiguity
      ? { ambiguity: d.ambiguity }
      : {}),
    ...(typeof d.upstreamQuote === "string"
      ? { upstreamQuote: d.upstreamQuote }
      : {}),
    ...(typeof d.downstreamQuote === "string"
      ? { downstreamQuote: d.downstreamQuote }
      : {}),
  };
}

// One bills.bill_reconciliations row, with the payload JSONB parsed.
export type BillReconciliationRow = {
  id: string;
  bill_id: string;
  section_citation: string;
  payload: TopicDiff;
  fingerprint: string | null;
  model: string | null;
  computed_at: string | null;
};
