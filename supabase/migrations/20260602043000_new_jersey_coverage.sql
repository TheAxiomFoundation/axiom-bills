-- Mark New Jersey live for Supabase.
UPDATE jurisdictions
   SET coverage = 'full'
 WHERE code = 'us-nj';
