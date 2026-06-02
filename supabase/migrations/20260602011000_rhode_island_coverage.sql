-- Mark Rhode Island live for existing Supabase databases.
UPDATE bills.jurisdictions
   SET coverage = 'full'
 WHERE code = 'us-ri';
