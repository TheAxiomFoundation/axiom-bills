-- Turn on row-level security across the bills schema without changing who can
-- read what.
--
-- Everything here is public reference data, so anon and authenticated keep
-- SELECT through an explicit policy. Writes still go through the service role,
-- which bypasses row-level security. With no write policy, a write grant added
-- by mistake later still changes nothing.
--
-- The views now run with their caller's rights, not their owner's. Later
-- migrations that replace one of these views must set security_invoker again,
-- because CREATE OR REPLACE VIEW resets view options.
--
-- This file can run more than once. To reverse it, run ALTER TABLE ... DISABLE
-- ROW LEVEL SECURITY on each table and ALTER VIEW ... RESET (security_invoker)
-- on each view.

alter table bills.jurisdictions enable row level security;
alter table bills.sessions enable row level security;
alter table bills.bills enable row level security;
alter table bills.bill_actions enable row level security;
alter table bills.bill_versions enable row level security;
alter table bills.bill_texts enable row level security;
alter table bills.bill_citations enable row level security;
alter table bills.axiom_encodings enable row level security;
alter table bills.encoded_rules enable row level security;
alter table bills.encoded_rule_atoms enable row level security;
alter table bills.rule_variants enable row level security;
alter table bills.encoding_graphs enable row level security;
alter table bills.bill_reconciliations enable row level security;
alter table bills.encode_queue enable row level security;

drop policy if exists "Public read" on bills.jurisdictions;
create policy "Public read" on bills.jurisdictions
  for select to anon, authenticated using (true);

drop policy if exists "Public read" on bills.sessions;
create policy "Public read" on bills.sessions
  for select to anon, authenticated using (true);

drop policy if exists "Public read" on bills.bills;
create policy "Public read" on bills.bills
  for select to anon, authenticated using (true);

drop policy if exists "Public read" on bills.bill_actions;
create policy "Public read" on bills.bill_actions
  for select to anon, authenticated using (true);

drop policy if exists "Public read" on bills.bill_versions;
create policy "Public read" on bills.bill_versions
  for select to anon, authenticated using (true);

drop policy if exists "Public read" on bills.bill_texts;
create policy "Public read" on bills.bill_texts
  for select to anon, authenticated using (true);

drop policy if exists "Public read" on bills.bill_citations;
create policy "Public read" on bills.bill_citations
  for select to anon, authenticated using (true);

drop policy if exists "Public read" on bills.axiom_encodings;
create policy "Public read" on bills.axiom_encodings
  for select to anon, authenticated using (true);

drop policy if exists "Public read" on bills.encoded_rules;
create policy "Public read" on bills.encoded_rules
  for select to anon, authenticated using (true);

drop policy if exists "Public read" on bills.encoded_rule_atoms;
create policy "Public read" on bills.encoded_rule_atoms
  for select to anon, authenticated using (true);

drop policy if exists "Public read" on bills.rule_variants;
create policy "Public read" on bills.rule_variants
  for select to anon, authenticated using (true);

drop policy if exists "Public read" on bills.encoding_graphs;
create policy "Public read" on bills.encoding_graphs
  for select to anon, authenticated using (true);

drop policy if exists "Public read" on bills.bill_reconciliations;
create policy "Public read" on bills.bill_reconciliations
  for select to anon, authenticated using (true);

drop policy if exists "Public read" on bills.encode_queue;
create policy "Public read" on bills.encode_queue
  for select to anon, authenticated using (true);

alter view bills.jurisdiction_summary set (security_invoker = true);
alter view bills.bill_list_summary set (security_invoker = true);
alter view bills.current_rule_patches set (security_invoker = true);

notify pgrst, 'reload schema';
