-- Track wire-up status per jurisdiction.
--   full     — scraper is live and tested end-to-end
--   stub     — file shape exists, status patterns done, scrape() returns []
--   planned  — listed in the roadmap, no code yet
--
-- Surfaced in the dashboard so we never quietly ship a "0 bills" card that
-- actually means "no scraper" instead of "no bills this session."

ALTER TABLE jurisdictions
  ADD COLUMN coverage TEXT NOT NULL DEFAULT 'planned'
  CHECK (coverage IN ('full', 'stub', 'planned'));

UPDATE jurisdictions SET coverage = 'full' WHERE code IN ('us', 'us-ny', 'us-co', 'us-de', 'us-md', 'us-mn');
