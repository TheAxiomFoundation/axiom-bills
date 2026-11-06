-- Where a refresh that follows an update feed stands, by session, and New York's
-- corrected chamber labels.
--
-- Both live in one file on purpose. The New York scraper now takes each bill's
-- chamber from the API, so a J, R or B print stops reading as lower chamber. The
-- sync matches bills on jurisdiction, session, chamber and number, so it would
-- insert a second row for each of those bills if the old labels remained. The
-- refresh workflow reads bills.refresh_state before it scrapes New York and stops
-- when the table is missing, so no run can reach the sync ahead of the relabel.
--
-- In production, 2,352 rows carry those prefixes, and every sponsor on them sits
-- in the Senate. The other prefixes keep their labels: S is upper, and A, K, C and
-- E are lower.
--
-- This file can run more than once: a later run creates nothing and changes no
-- row. To reverse it, drop the table and set those rows back to 'lower'.

begin;
set local lock_timeout = '2s';
set local statement_timeout = '60s';

create table if not exists bills.refresh_state (
  jurisdiction  text not null references bills.jurisdictions(code),
  session_name  text not null,
  feed_cursor   text not null,
  pending       text[] not null default '{}',
  updated_at    timestamptz not null default now(),
  primary key (jurisdiction, session_name)
);

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'refresh_state' and policyname = 'Public read') then
    create policy "Public read" on bills.refresh_state
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.refresh_state enable row level security;

grant select on bills.refresh_state to anon, authenticated;
grant all    on bills.refresh_state to service_role;

update bills.bills set chamber = 'upper'
 where jurisdiction = 'us-ny' and chamber = 'lower' and number ~ '^[JRB][0-9]';

commit;
