-- RuleSpec dependency-graph snapshots: one JSON payload per rulespec-*
-- repo, built by `precompute-graph` from a local checkout (module
-- imports, per-rule import atoms, formula references, deferred
-- outputs). The web Impact tab renders the payload directly; the bill
-- overlay is joined client-side.
CREATE TABLE IF NOT EXISTS encoding_graphs (
  repo            TEXT PRIMARY KEY,               -- rulespec repo name (e.g. rulespec-us)
  graph           TEXT NOT NULL,                  -- RulespecGraph JSON: meta/groups/sections/edges
  generated_from  TEXT,                           -- provenance: "<repo>@<git short sha>"
  generated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
