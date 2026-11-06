-- Where a refresh that follows an update feed stands, by session. pending holds
-- a JSON array of bill numbers. Supabase keeps the durable copy; CI runners start
-- from a fresh database and copy it down with hydrate-refresh-state.
CREATE TABLE IF NOT EXISTS refresh_state (
  jurisdiction  TEXT NOT NULL REFERENCES jurisdictions(code),
  session_name  TEXT NOT NULL,
  feed_cursor   TEXT NOT NULL,
  pending       TEXT NOT NULL DEFAULT '[]',
  updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (jurisdiction, session_name)
);

-- New York's J, R and B prints come from the Senate. The scraper used to label
-- everything without an S prefix as lower chamber.
UPDATE OR IGNORE bills SET chamber = 'upper'
 WHERE jurisdiction = 'us-ny' AND chamber = 'lower'
   AND (number GLOB 'J[0-9]*' OR number GLOB 'R[0-9]*' OR number GLOB 'B[0-9]*');
