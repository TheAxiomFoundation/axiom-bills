-- Materialized "does this bill touch corpus / rulespec" flags.
--
-- The list page's relevance filter used to fetch the newest 500 bills
-- and filter client-side — but rulespec-touching federal bills ranked
-- outside the newest-500 window, so the filter returned nothing.
-- Filtering must happen server-side, and scanning the heavy diffs JSONB
-- per request is this project's known statement-timeout trap, so the
-- flags are precomputed by precompute-diffs alongside diffs itself.
ALTER TABLE bills ADD COLUMN touches_corpus INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bills ADD COLUMN touches_rulespec INTEGER NOT NULL DEFAULT 0;
