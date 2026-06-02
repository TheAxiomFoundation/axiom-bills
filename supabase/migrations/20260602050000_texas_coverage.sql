-- Mark Texas live for Supabase.
UPDATE jurisdictions
   SET coverage = 'full'
 WHERE code = 'us-tx';
