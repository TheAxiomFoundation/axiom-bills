-- Local cache of axiom-corpus provisions, fetched from Supabase.
--
-- We mirror the columns the diff pipeline actually reads (body text +
-- heading + has_rulespec for the badge) plus the canonical citation_path
-- so a normalized bill_citation can join straight onto a provision.
--
-- Citation_path format (Axiom canonical): 'us/statute/26/213'.
-- The bill_citations.citation we extract is '26 USC 213'. The Python
-- side converts between the two.

CREATE TABLE IF NOT EXISTS corpus_provisions (
  citation_path  TEXT PRIMARY KEY,
  citation       TEXT NOT NULL,
  jurisdiction   TEXT NOT NULL,
  doc_type       TEXT NOT NULL,
  heading        TEXT,
  body           TEXT,
  effective_date TEXT,
  source_url     TEXT,
  has_rulespec   INTEGER NOT NULL DEFAULT 0,
  fetched_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_corpus_provisions_citation
  ON corpus_provisions(citation);
CREATE INDEX IF NOT EXISTS idx_corpus_provisions_jurisdiction
  ON corpus_provisions(jurisdiction);
