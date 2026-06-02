-- Mark Ohio live for existing Supabase databases.
UPDATE bills.jurisdictions
   SET coverage = 'full'
 WHERE code = 'us-oh';
