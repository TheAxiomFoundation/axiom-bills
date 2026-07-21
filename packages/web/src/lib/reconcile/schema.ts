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
