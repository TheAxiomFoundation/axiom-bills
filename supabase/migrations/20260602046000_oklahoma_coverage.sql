-- Mark Oklahoma live for Supabase.
UPDATE jurisdictions
   SET coverage = 'full'
 WHERE code = 'us-ok';
