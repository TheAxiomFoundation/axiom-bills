-- Mirror of db/migrations/060_bill_reconciliations.sql, in the bills
-- schema with Postgres-native types.
--
-- Per-section agentic bill ↔ encoding reconciliation verdicts, written
-- by `reconcile` and pushed by sync-supabase. The payload JSONB holds
-- { topic, section, billVsLaw: LayerDiff, modelVsLaw: LayerDiff }.

create table if not exists bills.bill_reconciliations (
  id               uuid primary key default gen_random_uuid(),
  bill_id          uuid not null references bills.bills(id) on delete cascade,
  section_citation text not null,
  payload          jsonb not null,
  fingerprint      text not null,
  model            text,
  computed_at      timestamptz not null default now(),
  unique (bill_id, section_citation)
);

create index if not exists idx_reconciliations_bill
  on bills.bill_reconciliations(bill_id);

grant select on bills.bill_reconciliations to anon, authenticated;
grant all    on bills.bill_reconciliations to service_role;
