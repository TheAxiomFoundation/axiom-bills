-- Re-encode trigger queue, materialized by `trigger-encodes` from the
-- pipeline's staleness signals:
--   needs_new_encoding — the bill adds provisions inside an encoded
--     program area that no existing rule file covers (encoder backlog);
--   stale_variant      — a bill's ops fingerprint changed and superseded
--     a previously drafted LLM variant for an encoded file;
--   enacted_touch      — an enacted/signed bill amends an encoded file,
--     so the baseline encoding itself is now stale.
--
-- One row per (bill, citation, reason). Rows are enqueue-once: a later
-- scan never resurrects an existing row, whatever its status — in
-- particular a human-dismissed row stays dismissed. The local
-- `trigger-encodes --run` runner stamps status/detail/resolved_at after
-- shelling out to `axiom-encode encode` (validate-only, never --apply).
CREATE TABLE IF NOT EXISTS encode_queue (
  id                   TEXT PRIMARY KEY,
  bill_id              TEXT NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  citation             TEXT NOT NULL,          -- legal citation for the encoder ('26 USC 32')
  corpus_citation_path TEXT,                   -- 'us/statute/26/32' from encoded_rules, when known
  reason               TEXT NOT NULL CHECK (reason IN
                         ('needs_new_encoding', 'stale_variant', 'enacted_touch')),
  status               TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
                         ('pending', 'ran', 'failed', 'dismissed')),
  detail               TEXT,                   -- runner outcome: exit code, output dir, stderr tail
  enqueued_at          TEXT NOT NULL DEFAULT (datetime('now')),
  resolved_at          TEXT,
  UNIQUE (bill_id, citation, reason)
);

CREATE INDEX IF NOT EXISTS idx_encode_queue_bill
  ON encode_queue(bill_id);
CREATE INDEX IF NOT EXISTS idx_encode_queue_status
  ON encode_queue(status);
