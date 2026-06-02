-- Mark Illinois live for hosted databases.
UPDATE jurisdictions
   SET coverage = 'full'
 WHERE code = 'us-il';

