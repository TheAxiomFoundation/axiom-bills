-- Mark New Mexico live for Supabase.
UPDATE jurisdictions
   SET coverage = 'full'
 WHERE code = 'us-nm';
