-- Bill ↔ encoding reconciliation verdicts, written by `reconcile`.
--
-- One row per (bill, touched section). The payload JSON holds the two
-- enum-constrained agentic verdicts:
--   { topic, section, billVsLaw: LayerDiff, modelVsLaw: LayerDiff }
-- where LayerDiff is { status, divergence, materiality, action,
-- confidence, rationale, ambiguity?, upstreamQuote?, downstreamQuote? }.
--
-- fingerprint = sha256 over canonical JSON of the section's ops (with
-- applied flags), before/after text shas, and the encoding file path —
-- unchanged inputs skip the LLM calls on re-runs.
CREATE TABLE IF NOT EXISTS bill_reconciliations (
  id               TEXT PRIMARY KEY,
  bill_id          TEXT NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  section_citation TEXT NOT NULL,
  payload          TEXT NOT NULL,
  fingerprint      TEXT NOT NULL,
  model            TEXT,
  computed_at      TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (bill_id, section_citation)
);

CREATE INDEX IF NOT EXISTS idx_reconciliations_bill
  ON bill_reconciliations(bill_id);
