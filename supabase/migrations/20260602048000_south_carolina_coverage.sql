-- Mark South Carolina live for Supabase.
UPDATE jurisdictions
   SET coverage = 'full'
 WHERE code = 'us-sc';
