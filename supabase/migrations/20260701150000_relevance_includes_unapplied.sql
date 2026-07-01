-- Relevance must fire on parsed amendment instructions, applied OR
-- unapplied. Unapplied ops are real amendment language the applier
-- couldn't mechanically verify against corpus text (drift; every
-- redesignate op) — counting only applied ops made such bills silently
-- invisible to the re-encode trigger (no chip, no flag, no variant).

create or replace view bills.bill_list_summary as
select
  b.id,
  b.jurisdiction,
  b.kind,
  b.current_status,
  coalesce(enc.matched_encodings, '[]'::jsonb) as matched_encodings,
  coalesce(cor.matched_corpus,    '[]'::jsonb) as matched_corpus
from bills.bills b
left join lateral (
  select jsonb_agg(e order by e->>'file_path') as matched_encodings
  from (
    select distinct on (sec->'encoding'->>'file_path')
      jsonb_build_object(
        'repo',       sec->'encoding'->>'repo',
        'kind',       sec->'encoding'->>'kind',
        'citation',   sec->'encoding'->>'citation',
        'file_path',  sec->'encoding'->>'file_path',
        'github_url', sec->'encoding'->>'github_url'
      ) as e
    from jsonb_array_elements(coalesce(b.diffs->'sections', '[]'::jsonb)) sec
    where jsonb_typeof(sec->'encoding') = 'object'
      and (
        (jsonb_typeof(sec->'applied_ops') = 'array'
         and jsonb_array_length(sec->'applied_ops') > 0)
        or
        (jsonb_typeof(sec->'unapplied_ops') = 'array'
         and jsonb_array_length(sec->'unapplied_ops') > 0)
      )
  ) s
) enc on true
left join lateral (
  select jsonb_agg(c order by c->>'citation_path') as matched_corpus
  from (
    select distinct on (sec->>'citation_path')
      jsonb_build_object(
        'citation',      sec->>'citation',
        'citation_path', sec->>'citation_path',
        'heading',       sec->>'heading',
        'axiom_url',     sec->>'axiom_url'
      ) as c
    from jsonb_array_elements(coalesce(b.diffs->'sections', '[]'::jsonb)) sec
    where coalesce((sec->>'in_corpus')::boolean, false) is true
      and coalesce(sec->>'citation_path', '') <> ''
      and (
        (jsonb_typeof(sec->'applied_ops') = 'array'
         and jsonb_array_length(sec->'applied_ops') > 0)
        or
        (jsonb_typeof(sec->'unapplied_ops') = 'array'
         and jsonb_array_length(sec->'unapplied_ops') > 0)
      )
  ) s
) cor on true;

grant select on bills.bill_list_summary to anon, authenticated, service_role;

-- Re-backfill the materialized flags with the same predicate.
update bills.bills b set
  touches_rulespec = exists (
    select 1
    from jsonb_array_elements(coalesce(b.diffs->'sections', '[]'::jsonb)) sec
    where jsonb_typeof(sec->'encoding') = 'object'
      and (
        (jsonb_typeof(sec->'applied_ops') = 'array'
         and jsonb_array_length(sec->'applied_ops') > 0)
        or
        (jsonb_typeof(sec->'unapplied_ops') = 'array'
         and jsonb_array_length(sec->'unapplied_ops') > 0)
      )
  ),
  touches_corpus = exists (
    select 1
    from jsonb_array_elements(coalesce(b.diffs->'sections', '[]'::jsonb)) sec
    where coalesce((sec->>'in_corpus')::boolean, false)
      and coalesce(sec->>'citation_path', '') <> ''
      and (
        (jsonb_typeof(sec->'applied_ops') = 'array'
         and jsonb_array_length(sec->'applied_ops') > 0)
        or
        (jsonb_typeof(sec->'unapplied_ops') = 'array'
         and jsonb_array_length(sec->'unapplied_ops') > 0)
      )
  )
where b.diffs is not null;
