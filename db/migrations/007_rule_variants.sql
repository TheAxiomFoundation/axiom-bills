-- Pipeline B variants: per-bill patched rule YAML.
--
-- One row per (bill, rule_file) pair where the bill's amendments touch
-- a rule encoded against the targeted section. Stores the patched YAML
-- in full so the frontend can render a diff and an eventual rulespec-us
-- PR can commit the file verbatim.
CREATE TABLE IF NOT EXISTS rule_variants (
  id                  TEXT PRIMARY KEY,
  bill_id             TEXT NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  encoding_id         TEXT NOT NULL REFERENCES axiom_encodings(id) ON DELETE CASCADE,
  file_path           TEXT NOT NULL,
  tier                TEXT NOT NULL,          -- substitution | list | structural | no_op
  patched_rule_names  TEXT NOT NULL,          -- JSON list of rule names patched
  baseline_yaml       TEXT,                   -- nullable: only stored when patched
  patched_yaml        TEXT,                   -- nullable for no_op/list/structural
  diff_summary        TEXT,
  note                TEXT,
  effective_from      TEXT,                   -- ISO date the variant becomes active
  computed_at         TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (bill_id, file_path)
);

CREATE INDEX IF NOT EXISTS idx_variants_bill ON rule_variants(bill_id);
CREATE INDEX IF NOT EXISTS idx_variants_tier ON rule_variants(tier);
