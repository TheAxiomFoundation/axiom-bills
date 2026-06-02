-- Mark Indiana live for Supabase/Postgres.
UPDATE jurisdictions
   SET coverage = 'full'
 WHERE code = 'us-in';
