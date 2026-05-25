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
  coverage     TEXT NOT NULL DEFAULT 'planned'
    CHECK (coverage IN ('full', 'stub', 'planned')),
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
  kind                TEXT NOT NULL DEFAULT 'substantive'
    CHECK (kind IN ('substantive','placeholder','ceremonial',
                    'appropriations','procedural','vehicle','unknown')),
  first_seen_at       TEXT NOT NULL DEFAULT (datetime('now')),
  last_scraped_at     TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (jurisdiction, session_id, chamber, number)
);

CREATE INDEX IF NOT EXISTS idx_bills_jurisdiction_status
  ON bills(jurisdiction, current_status);
CREATE INDEX IF NOT EXISTS idx_bills_status_at
  ON bills(current_status_at DESC);
CREATE INDEX IF NOT EXISTS idx_bills_kind
  ON bills(jurisdiction, kind);

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
INSERT OR IGNORE INTO jurisdictions (code, name, level, source_url, coverage) VALUES
  ('us',    'United States', 'federal', 'https://api.congress.gov',         'full'),
  ('us-ny', 'New York',      'state',   'https://legislation.nysenate.gov', 'full'),
  ('us-co', 'Colorado',      'state',   'https://leg.colorado.gov',         'stub'),
  ('us-mn', 'Minnesota',     'state',   'https://www.revisor.mn.gov',       'stub');

-- Roadmap for the 49-state buildout. Listed here so the dashboard's
-- "States we have not yet wired up" view is one query, not a separate
-- hard-coded list.
INSERT OR IGNORE INTO jurisdictions (code, name, level, source_url, coverage) VALUES
  ('us-al', 'Alabama',        'state', 'https://alison.legislature.state.al.us', 'planned'),
  ('us-ak', 'Alaska',         'state', 'https://www.akleg.gov',                   'planned'),
  ('us-az', 'Arizona',        'state', 'https://www.azleg.gov',                   'planned'),
  ('us-ar', 'Arkansas',       'state', 'https://www.arkleg.state.ar.us',          'planned'),
  ('us-ca', 'California',     'state', 'https://leginfo.legislature.ca.gov',      'planned'),
  ('us-ct', 'Connecticut',    'state', 'https://www.cga.ct.gov',                  'planned'),
  ('us-de', 'Delaware',       'state', 'https://legis.delaware.gov',              'planned'),
  ('us-fl', 'Florida',        'state', 'https://www.flsenate.gov',                'planned'),
  ('us-ga', 'Georgia',        'state', 'https://www.legis.ga.gov',                'planned'),
  ('us-hi', 'Hawaii',         'state', 'https://www.capitol.hawaii.gov',          'planned'),
  ('us-id', 'Idaho',          'state', 'https://legislature.idaho.gov',           'planned'),
  ('us-il', 'Illinois',       'state', 'https://www.ilga.gov',                    'planned'),
  ('us-in', 'Indiana',        'state', 'https://iga.in.gov',                      'planned'),
  ('us-ia', 'Iowa',           'state', 'https://www.legis.iowa.gov',              'planned'),
  ('us-ks', 'Kansas',         'state', 'https://kslegislature.org',               'planned'),
  ('us-ky', 'Kentucky',       'state', 'https://legislature.ky.gov',              'planned'),
  ('us-la', 'Louisiana',      'state', 'https://www.legis.la.gov',                'planned'),
  ('us-me', 'Maine',          'state', 'https://legislature.maine.gov',           'planned'),
  ('us-md', 'Maryland',       'state', 'https://mgaleg.maryland.gov',             'planned'),
  ('us-ma', 'Massachusetts',  'state', 'https://malegislature.gov',               'planned'),
  ('us-mi', 'Michigan',       'state', 'https://www.legislature.mi.gov',          'planned'),
  ('us-ms', 'Mississippi',    'state', 'http://billstatus.ls.state.ms.us',        'planned'),
  ('us-mo', 'Missouri',       'state', 'https://www.house.mo.gov',                'planned'),
  ('us-mt', 'Montana',        'state', 'https://leg.mt.gov',                      'planned'),
  ('us-ne', 'Nebraska',       'state', 'https://nebraskalegislature.gov',         'planned'),
  ('us-nv', 'Nevada',         'state', 'https://www.leg.state.nv.us',             'planned'),
  ('us-nh', 'New Hampshire',  'state', 'https://gencourt.state.nh.us',            'planned'),
  ('us-nj', 'New Jersey',     'state', 'https://www.njleg.state.nj.us',           'planned'),
  ('us-nm', 'New Mexico',     'state', 'https://www.nmlegis.gov',                 'planned'),
  ('us-nc', 'North Carolina', 'state', 'https://www.ncleg.gov',                   'planned'),
  ('us-nd', 'North Dakota',   'state', 'https://www.legis.nd.gov',                'planned'),
  ('us-oh', 'Ohio',           'state', 'https://www.legislature.ohio.gov',        'planned'),
  ('us-ok', 'Oklahoma',       'state', 'https://www.oklegislature.gov',           'planned'),
  ('us-or', 'Oregon',         'state', 'https://olis.oregonlegislature.gov',      'planned'),
  ('us-pa', 'Pennsylvania',   'state', 'https://www.palegis.us',                  'planned'),
  ('us-ri', 'Rhode Island',   'state', 'https://www.rilegislature.gov',           'planned'),
  ('us-sc', 'South Carolina', 'state', 'https://www.scstatehouse.gov',            'planned'),
  ('us-sd', 'South Dakota',   'state', 'https://sdlegislature.gov',               'planned'),
  ('us-tn', 'Tennessee',      'state', 'https://wapp.capitol.tn.gov',             'planned'),
  ('us-tx', 'Texas',          'state', 'https://capitol.texas.gov',               'planned'),
  ('us-ut', 'Utah',           'state', 'https://le.utah.gov',                     'planned'),
  ('us-vt', 'Vermont',        'state', 'https://legislature.vermont.gov',         'planned'),
  ('us-va', 'Virginia',       'state', 'https://lis.virginia.gov',                'planned'),
  ('us-wa', 'Washington',     'state', 'https://app.leg.wa.gov',                  'planned'),
  ('us-wv', 'West Virginia',  'state', 'https://www.wvlegislature.gov',           'planned'),
  ('us-wi', 'Wisconsin',      'state', 'https://docs.legis.wisconsin.gov',        'planned'),
  ('us-wy', 'Wyoming',        'state', 'https://wyoleg.gov',                      'planned'),
  ('us-dc', 'District of Columbia', 'state', 'https://lims.dccouncil.gov',        'planned');
