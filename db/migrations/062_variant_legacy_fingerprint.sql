-- The fingerprint a variant's inputs had under the definition that
-- predates FINGERPRINT_SCHEME (sha256 over the four parsed op fields,
-- the applied flags and the baseline YAML; no prefix). Local only: it
-- is never synced. When a stored fingerprint is from that older scheme,
-- comparing it with this value tells "only the definition changed"
-- apart from "the bill or baseline changed", so the second still marks
-- the LLM proposal superseded and the first does not.
ALTER TABLE rule_variants ADD COLUMN legacy_ops_fingerprint TEXT;
