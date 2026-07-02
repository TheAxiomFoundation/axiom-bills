-- Mirror of db/migrations/058_needs_new_encoding.sql, plus backfill.
--
-- Bills that add NEW provisions inside encoded program areas: their
-- amendment targets nest with encoded citations, but no existing rule
-- file is affected. Encoder-backlog items — distinct from
-- touches_rulespec (re-encode trigger) and from unencoded territory.

alter table bills.bills
  add column if not exists needs_new_encoding boolean not null default false;

create index if not exists idx_bills_needs_encoding
  on bills.bills(jurisdiction) where needs_new_encoding;

-- Backfill: sections with parsed ops, no rail encoding, but a related
-- (nested either way) encoded citation.
update bills.bills b set needs_new_encoding = exists (
  select 1
  from jsonb_array_elements(coalesce(b.diffs->'sections', '[]'::jsonb)) sec
  where jsonb_typeof(sec->'encoding') <> 'object'
    and (
      (jsonb_typeof(sec->'applied_ops') = 'array'
       and jsonb_array_length(sec->'applied_ops') > 0)
      or
      (jsonb_typeof(sec->'unapplied_ops') = 'array'
       and jsonb_array_length(sec->'unapplied_ops') > 0)
    )
    and exists (
      select 1 from bills.axiom_encodings e
      where e.citation = sec->>'citation'
         or e.citation like (sec->>'citation') || '(%'
         or e.citation like (sec->>'citation') || '.%'
         or sec->>'citation' like e.citation || '(%'
         or sec->>'citation' like e.citation || '.%'
    )
) where b.diffs is not null;
