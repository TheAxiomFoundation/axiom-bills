-- axiom-bills initial schema (SQLite)
--
-- Design notes:
-- * Bill primary key is (jurisdiction, session, chamber, number). Never the
--   number alone — bill numbers collide across sessions and chambers.
-- * Actions are append-only. Status is derived from the highest-ranked
--   action with a non-null normalized_status. Never overwrite an action.
-- * normalized_status is a TEXT field with a CHECK constraint (SQLite has
--   no enum type). The Python writer keeps the vocabulary stable.
-- * subjects and sponsors stored as JSON text (SQLite has no array).
-- * Timestamps stored as ISO8601 strings.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS jurisdictions (
  code         TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  level        TEXT NOT NULL CHECK (level IN ('federal', 'state')),
  source_url   TEXT NOT NULL,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
  id              TEXT PRIMARY KEY,                      -- uuid hex
  jurisdiction    TEXT NOT NULL REFERENCES jurisdictions(code),
  name            TEXT NOT NULL,
  start_date      TEXT,
  end_date        TEXT,
  is_current      INTEGER NOT NULL DEFAULT 0,            -- bool 0/1
  UNIQUE (jurisdiction, name)
);

CREATE INDEX IF NOT EXISTS idx_sessions_current
  ON sessions(jurisdiction) WHERE is_current = 1;

CREATE TABLE IF NOT EXISTS bills (
  id                  TEXT PRIMARY KEY,
  jurisdiction        TEXT NOT NULL REFERENCES jurisdictions(code),
  session_id          TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  chamber             TEXT NOT NULL CHECK (chamber IN ('lower','upper','joint','executive')),
  number              TEXT NOT NULL,
  title               TEXT,
  summary             TEXT,
  subjects            TEXT NOT NULL DEFAULT '[]',        -- JSON array
  sponsors            TEXT NOT NULL DEFAULT '[]',        -- JSON array of objects
  source_url          TEXT NOT NULL,
  current_status      TEXT NOT NULL DEFAULT 'unknown'
    CHECK (current_status IN (
      'introduced','in_committee','passed_chamber','passed_both',
      'enrolled','signed','enacted','vetoed','veto_overridden','failed','unknown'
    )),
  current_status_at   TEXT,
  first_seen_at       TEXT NOT NULL DEFAULT (datetime('now')),
  last_scraped_at     TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (jurisdiction, session_id, chamber, number)
);

CREATE INDEX IF NOT EXISTS idx_bills_jurisdiction_status
  ON bills(jurisdiction, current_status);
CREATE INDEX IF NOT EXISTS idx_bills_status_at
  ON bills(current_status_at DESC);

CREATE TABLE IF NOT EXISTS bill_actions (
  id                  TEXT PRIMARY KEY,
  bill_id             TEXT NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  occurred_at         TEXT NOT NULL,
  chamber             TEXT CHECK (chamber IN ('lower','upper','joint','executive')),
  action_text         TEXT NOT NULL,
  normalized_status   TEXT
    CHECK (normalized_status IS NULL OR normalized_status IN (
      'introduced','in_committee','passed_chamber','passed_both',
      'enrolled','signed','enacted','vetoed','veto_overridden','failed','unknown'
    )),
  source_url          TEXT,
  fingerprint         TEXT NOT NULL,
  ingested_at         TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (bill_id, fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_actions_bill_occurred
  ON bill_actions(bill_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_actions_status_change
  ON bill_actions(normalized_status, occurred_at DESC)
  WHERE normalized_status IS NOT NULL;

CREATE TABLE IF NOT EXISTS bill_versions (
  id            TEXT PRIMARY KEY,
  bill_id       TEXT NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  label         TEXT NOT NULL,
  source_url    TEXT NOT NULL,
  format        TEXT NOT NULL,
  text_sha256   TEXT,
  fetched_at    TEXT,
  UNIQUE (bill_id, label)
);

CREATE TABLE IF NOT EXISTS scrape_runs (
  id                 TEXT PRIMARY KEY,
  jurisdiction       TEXT NOT NULL REFERENCES jurisdictions(code),
  started_at         TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at        TEXT,
  bills_seen         INTEGER NOT NULL DEFAULT 0,
  bills_new          INTEGER NOT NULL DEFAULT 0,
  actions_new        INTEGER NOT NULL DEFAULT 0,
  error              TEXT,
  notes              TEXT
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_jurisdiction_started
  ON scrape_runs(jurisdiction, started_at DESC);

-- Seed jurisdictions covered by the prototype.
INSERT OR IGNORE INTO jurisdictions (code, name, level, source_url) VALUES
  ('us',    'United States', 'federal', 'https://api.congress.gov'),
  ('us-ny', 'New York',      'state',   'https://legislation.nysenate.gov'),
  ('us-co', 'Colorado',      'state',   'https://leg.colorado.gov'),
  ('us-mn', 'Minnesota',     'state',   'https://www.revisor.mn.gov');
