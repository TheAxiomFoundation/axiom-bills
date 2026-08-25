-- Mirror of db/migrations/061_encode_queue.sql, in the bills schema
-- with Postgres-native types.
--
-- Re-encode trigger queue, materialized by `trigger-encodes` and pushed
-- by sync-supabase. One row per (bill, citation, reason); rows are
-- enqueue-once so a dismissed row is never resurrected by a later scan.

create table if not exists bills.encode_queue (
  id                   uuid primary key default gen_random_uuid(),
  bill_id              uuid not null references bills.bills(id) on delete cascade,
  citation             text not null,
  corpus_citation_path text,
  reason               text not null check (reason in
                         ('needs_new_encoding', 'stale_variant', 'enacted_touch')),
  status               text not null default 'pending' check (status in
                         ('pending', 'ran', 'failed', 'dismissed')),
  detail               text,
  enqueued_at          timestamptz not null default now(),
  resolved_at          timestamptz,
  unique (bill_id, citation, reason)
);

create index if not exists idx_encode_queue_bill
  on bills.encode_queue(bill_id);
create index if not exists idx_encode_queue_status
  on bills.encode_queue(status);

grant select on bills.encode_queue to anon, authenticated;
grant all    on bills.encode_queue to service_role;
