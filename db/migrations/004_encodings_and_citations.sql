-- Bridge between the bill stream and Axiom encodings.
--
-- axiom_encodings: file-tree snapshot of which RuleSpec YAMLs exist in
--   the local rulespec-* repos. The file *path* encodes the citation
--   (statutes/26/32/a/1.yaml ↔ 26 USC 32(a)(1)), so we store both the
--   normalized citation string and the path for cheap matching.
--
-- bill_citations: extracted from bill summary and full text. Stored
--   with `source` so we can audit which citations came from each
--   stream and re-extract when patterns change.
--
-- bill_texts: full bill text we've downloaded, keyed by version label.
--   Stored as TEXT (not in object storage) for prototype simplicity;
--   moves to R2 once we exceed a megabyte or two per bill.

CREATE TABLE IF NOT EXISTS axiom_encodings (
  id              TEXT PRIMARY KEY,
  jurisdiction    TEXT NOT NULL,            -- 'us' for rulespec-us
  repo            TEXT NOT NULL,            -- 'rulespec-us'
  kind            TEXT NOT NULL CHECK (kind IN ('statute', 'regulation', 'policy')),
  citation        TEXT NOT NULL,            -- normalized: '26 USC 32(a)(1)' or '7 CFR 273.3'
  file_path       TEXT NOT NULL UNIQUE,     -- 'statutes/26/32/a/1.yaml'
  indexed_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_encodings_citation
  ON axiom_encodings(citation);
CREATE INDEX IF NOT EXISTS idx_encodings_jurisdiction
  ON axiom_encodings(jurisdiction);

CREATE TABLE IF NOT EXISTS bill_citations (
  id                  TEXT PRIMARY KEY,
  bill_id             TEXT NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  raw                 TEXT NOT NULL,        -- exact substring as found in bill
  citation            TEXT NOT NULL,        -- normalized for matching
  source              TEXT NOT NULL
    CHECK (source IN ('title', 'summary', 'text', 'action')),
  extracted_at        TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (bill_id, citation, source)
);

CREATE INDEX IF NOT EXISTS idx_bill_citations_bill
  ON bill_citations(bill_id);
CREATE INDEX IF NOT EXISTS idx_bill_citations_citation
  ON bill_citations(citation);

CREATE TABLE IF NOT EXISTS bill_texts (
  id                  TEXT PRIMARY KEY,
  bill_id             TEXT NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  version_label       TEXT NOT NULL,        -- 'introduced-html', 'enrolled-pdf', etc.
  source_url          TEXT NOT NULL,
  format              TEXT NOT NULL,        -- 'html', 'pdf', 'xml', 'txt'
  text                TEXT NOT NULL,
  text_sha256         TEXT NOT NULL,
  fetched_at          TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (bill_id, version_label)
);
