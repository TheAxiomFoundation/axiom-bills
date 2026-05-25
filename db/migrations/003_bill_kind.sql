-- Add bill_kind classification.
--
-- A bill's *status* says where it is in the legislative process.
-- A bill's *kind* says what it is at all: is this a substantive policy
-- ask, or a placeholder, ceremonial resolution, appropriations bill, a
-- procedural rules bill, or a strip-and-replace vehicle?
--
-- Defaulting to 'substantive' is correct for the long tail; classifier
-- code in scrapers/<jurisdiction>/bill/kind.py overrides where signals
-- say otherwise. Down-stream consumers (Pipeline B, dashboards) filter
-- on this so only substantive enacted bills trigger encoding work.

ALTER TABLE bills
  ADD COLUMN kind TEXT NOT NULL DEFAULT 'substantive'
  CHECK (kind IN (
    'substantive',
    'placeholder',
    'ceremonial',
    'appropriations',
    'procedural',
    'vehicle',
    'unknown'
  ));

CREATE INDEX IF NOT EXISTS idx_bills_kind ON bills(jurisdiction, kind);
