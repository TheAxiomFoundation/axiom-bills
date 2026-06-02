-- Mark Iowa live for hosted databases.
UPDATE jurisdictions
   SET coverage = 'full'
 WHERE code = 'us-ia';

