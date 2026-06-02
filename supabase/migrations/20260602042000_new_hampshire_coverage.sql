-- Mark New Hampshire live for Supabase.
UPDATE jurisdictions
   SET coverage = 'full'
 WHERE code = 'us-nh';

