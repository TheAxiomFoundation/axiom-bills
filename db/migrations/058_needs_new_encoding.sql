-- Bills that add NEW provisions inside encoded program areas (their
-- amendment targets nest with encoded citations, but no existing rule
-- file is affected). These are encoder-backlog items — distinct from
-- touches_rulespec (re-encode trigger) and from unencoded territory.
ALTER TABLE bills ADD COLUMN needs_new_encoding INTEGER NOT NULL DEFAULT 0;
