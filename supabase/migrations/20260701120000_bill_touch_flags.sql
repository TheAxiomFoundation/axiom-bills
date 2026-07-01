-- Mirror of db/migrations/057_bill_touch_flags.sql, plus backfill.
--
-- The relevance filter needs server-side filtering: the list query is
-- capped at 500 rows ordered by last action, and every rulespec-touching
-- federal bill ranked outside that window, so client-side filtering
-- showed nothing. Scanning diffs JSONB per request is the known
-- statement-timeout trap; instead the flags are materialized here and
-- maintained by precompute-diffs → sync.

alter table bills.bills
  add column if not exists touches_corpus   boolean not null default false,
  add column if not exists touches_rulespec boolean not null default false;

-- Backfill from existing diffs, using the same predicate as
-- bills.bill_list_summary (encoding/corpus match with >=1 APPLIED op).
update bills.bills b set
  touches_rulespec = exists (
    select 1
    from jsonb_array_elements(coalesce(b.diffs->'sections', '[]'::jsonb)) sec
    where jsonb_typeof(sec->'encoding') = 'object'
      and jsonb_typeof(sec->'applied_ops') = 'array'
      and jsonb_array_length(sec->'applied_ops') > 0
  ),
  touches_corpus = exists (
    select 1
    from jsonb_array_elements(coalesce(b.diffs->'sections', '[]'::jsonb)) sec
    where coalesce((sec->>'in_corpus')::boolean, false)
      and coalesce(sec->>'citation_path', '') <> ''
      and jsonb_typeof(sec->'applied_ops') = 'array'
      and jsonb_array_length(sec->'applied_ops') > 0
  )
where b.diffs is not null;

-- Partial indexes: the filter is always "in this jurisdiction, flagged".
create index if not exists idx_bills_touches_rulespec
  on bills.bills(jurisdiction) where touches_rulespec;
create index if not exists idx_bills_touches_corpus
  on bills.bills(jurisdiction) where touches_corpus;
