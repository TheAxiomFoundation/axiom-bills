-- Mark implemented state scrapers live in deployed Supabase projects.
update bills.jurisdictions
   set coverage = 'full'
 where code in ('us-co', 'us-de', 'us-mn');
