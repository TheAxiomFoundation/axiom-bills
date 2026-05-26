-- Per-jurisdiction roll-up so the home page can render in ONE query
-- instead of 52 × 3 = 156 sequential PostgREST round-trips.
create or replace view bills.jurisdiction_summary as
select
  j.code,
  j.name,
  j.level,
  j.coverage,
  j.source_url,
  coalesce(b.bill_count,    0) as bill_count,
  coalesce(b.enacted_count, 0) as enacted_count,
  b.last_scraped_at
from bills.jurisdictions j
left join (
  select
    jurisdiction,
    count(*) as bill_count,
    count(*) filter (where current_status = 'enacted') as enacted_count,
    max(last_scraped_at) as last_scraped_at
  from bills.bills
  group by jurisdiction
) b on b.jurisdiction = j.code;

grant select on bills.jurisdiction_summary to anon, authenticated, service_role;
