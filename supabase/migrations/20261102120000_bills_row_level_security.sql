-- Turn on row-level security across the bills schema without changing who can
-- read what.
--
-- Everything here is public reference data, so anon and authenticated keep
-- SELECT through an explicit policy. Writes still go through the service role,
-- which bypasses row-level security. With no write policy, an insert, update or
-- delete grant added by mistake later still changes no row. Row-level security
-- doesn't cover TRUNCATE, REFERENCES, TRIGGER or MAINTAIN, so neither role may
-- hold them.
--
-- The views now run with their caller's rights, not their owner's. A migration
-- that replaces one of them must create it with (security_invoker = true),
-- because CREATE OR REPLACE VIEW resets view options.
--
-- Under row-level security, the planner compares a value with a column's most
-- common values only through a leakproof operator, and PostgreSQL doesn't mark
-- enum equality leakproof. For kind it then treats every kind as equally
-- common and overestimates a rare one, so it can plan a list of one rare kind
-- as a walk of idx_bills_status_at across every jurisdiction. The new index
-- keeps that walk inside one jurisdiction.
--
-- Statement order matters on a database that is serving reads:
-- - One transaction with a lock timeout: a lock wait aborts the whole file, so
--   a retry starts clean.
-- - The index first: it blocks writers while it builds, but no reader.
-- - The views next, before their tables, the order in which a view's readers
--   take locks.
-- - Then the tables, in the order the web app's reads lock them, so the bill
--   page (bills, then sessions, jurisdictions, actions, versions, texts and
--   citations) can't deadlock with this file.
-- - Each table gets its policy before row-level security, so anon never meets
--   a table with row-level security and no policy, even if these statements
--   run one at a time.
--
-- This file can run more than once: a later run creates no policy and changes
-- nothing. To reverse it, run ALTER TABLE ... DISABLE ROW LEVEL SECURITY on
-- each table and ALTER VIEW ... RESET (security_invoker) on each view.

begin;
set local lock_timeout = '2s';
set local statement_timeout = '60s';

create index if not exists idx_bills_jurisdiction_status_at
  on bills.bills (jurisdiction, current_status_at desc nulls last, id);

alter view bills.jurisdiction_summary set (security_invoker = true);
alter view bills.bill_list_summary set (security_invoker = true);
alter view bills.current_rule_patches set (security_invoker = true);

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'bills' and policyname = 'Public read') then
    create policy "Public read" on bills.bills
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.bills enable row level security;

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'sessions' and policyname = 'Public read') then
    create policy "Public read" on bills.sessions
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.sessions enable row level security;

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'jurisdictions' and policyname = 'Public read') then
    create policy "Public read" on bills.jurisdictions
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.jurisdictions enable row level security;

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'bill_actions' and policyname = 'Public read') then
    create policy "Public read" on bills.bill_actions
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.bill_actions enable row level security;

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'bill_versions' and policyname = 'Public read') then
    create policy "Public read" on bills.bill_versions
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.bill_versions enable row level security;

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'bill_texts' and policyname = 'Public read') then
    create policy "Public read" on bills.bill_texts
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.bill_texts enable row level security;

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'bill_citations' and policyname = 'Public read') then
    create policy "Public read" on bills.bill_citations
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.bill_citations enable row level security;

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'rule_variants' and policyname = 'Public read') then
    create policy "Public read" on bills.rule_variants
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.rule_variants enable row level security;

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'axiom_encodings' and policyname = 'Public read') then
    create policy "Public read" on bills.axiom_encodings
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.axiom_encodings enable row level security;

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'encoded_rules' and policyname = 'Public read') then
    create policy "Public read" on bills.encoded_rules
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.encoded_rules enable row level security;

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'encoded_rule_atoms' and policyname = 'Public read') then
    create policy "Public read" on bills.encoded_rule_atoms
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.encoded_rule_atoms enable row level security;

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'encoding_graphs' and policyname = 'Public read') then
    create policy "Public read" on bills.encoding_graphs
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.encoding_graphs enable row level security;

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'bill_reconciliations' and policyname = 'Public read') then
    create policy "Public read" on bills.bill_reconciliations
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.bill_reconciliations enable row level security;

do $$ begin
  if not exists (select from pg_policies where schemaname = 'bills'
                 and tablename = 'encode_queue' and policyname = 'Public read') then
    create policy "Public read" on bills.encode_queue
      for select to anon, authenticated using (true);
  end if;
end $$;
alter table bills.encode_queue enable row level security;

notify pgrst, 'reload schema';

commit;
