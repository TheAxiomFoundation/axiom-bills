-- Rule-level index from rulespec-* YAMLs.
--
-- Per docs/corpus-encoding-mapping.md (axiom-architecture PR #11):
-- Pipeline B's trigger benefits from rule-level granularity, not just
-- file-level. A bill amendment that overlaps any rule's proof-atom
-- text is a strong signal that rule needs re-encoding. Indexing those
-- atoms locally so the API can match against them without re-reading
-- YAMLs per request.

CREATE TABLE IF NOT EXISTS encoded_rules (
  id                       TEXT PRIMARY KEY,
  encoding_id              TEXT NOT NULL REFERENCES axiom_encodings(id) ON DELETE CASCADE,
  rule_name                TEXT NOT NULL,
  rule_kind                TEXT,
  rule_source              TEXT NOT NULL,      -- '26 USC 213(a)' — subsection-level
  rule_dtype               TEXT,
  module_corpus_citation_path TEXT,            -- 'us/statute/26/213'
  indexed_at               TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_encoded_rules_source
  ON encoded_rules(rule_source);
CREATE INDEX IF NOT EXISTS idx_encoded_rules_encoding
  ON encoded_rules(encoding_id);

CREATE TABLE IF NOT EXISTS encoded_rule_atoms (
  id              TEXT PRIMARY KEY,
  rule_id         TEXT NOT NULL REFERENCES encoded_rules(id) ON DELETE CASCADE,
  atom_path       TEXT,                        -- e.g. 'versions[0].formula'
  atom_kind       TEXT,                        -- 'parameter' | 'amount' | 'condition' | 'formula'
  corpus_citation_path TEXT,                   -- 'us/statute/26/213'
  text            TEXT NOT NULL                -- verbatim corpus prose
);

CREATE INDEX IF NOT EXISTS idx_atoms_rule ON encoded_rule_atoms(rule_id);
CREATE INDEX IF NOT EXISTS idx_atoms_corpus_path
  ON encoded_rule_atoms(corpus_citation_path);
