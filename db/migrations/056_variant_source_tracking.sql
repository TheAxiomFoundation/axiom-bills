-- Track which inputs a rule_variant was computed from, so re-runs can
-- tell "nothing changed — keep the (possibly LLM-proposed) patch" apart
-- from "the bill text or baseline moved — the old patch is stale".
--
-- source_ops_fingerprint: sha256 over the canonical JSON of the ops fed
--   to the reencoder plus the baseline YAML. Same fingerprint ⇒ same
--   inputs ⇒ the stored variant (and any LLM proposal on it) is current.
-- source_text_sha256: sha256 of the bill text the diffs were parsed
--   from, copied through from bills.diffs for provenance.
ALTER TABLE rule_variants ADD COLUMN source_ops_fingerprint TEXT;
ALTER TABLE rule_variants ADD COLUMN source_text_sha256 TEXT;

-- Codify the bills.diffs column precompute-diffs used to add at
-- runtime, so a freshly migrated DB matches the code's expectations.
ALTER TABLE bills ADD COLUMN diffs TEXT;
