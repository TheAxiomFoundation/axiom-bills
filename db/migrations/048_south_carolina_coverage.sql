-- Mark South Carolina live for existing SQLite databases.
UPDATE jurisdictions
   SET coverage = 'full'
 WHERE code = 'us-sc';
