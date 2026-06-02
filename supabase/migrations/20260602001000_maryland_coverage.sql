-- Mark Maryland live in deployed Supabase projects.
update bills.jurisdictions
   set coverage = 'full'
 where code = 'us-md';
