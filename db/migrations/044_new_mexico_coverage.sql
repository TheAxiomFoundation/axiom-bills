-- Mark New Mexico live for existing SQLite databases.
UPDATE jurisdictions
   SET coverage = 'full'
 WHERE code = 'us-nm';
