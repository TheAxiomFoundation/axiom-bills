-- Mark implemented state scrapers live for existing SQLite databases.
UPDATE jurisdictions
   SET coverage = 'full'
 WHERE code IN ('us-co', 'us-de', 'us-mn');
