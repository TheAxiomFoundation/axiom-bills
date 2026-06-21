-- Lean per-bill "matched" summary for the jurisdiction list page.
--
-- The list page must NEVER pull the heavy bills.diffs JSONB (precomputed
-- full-text diffs). Fetching diffs for up to 500 rows blew past the
-- statement timeout on large jurisdictions (federal) and returned 500s.
--
-- The list only needs the *derived* matched_encodings / matched_corpus —
-- which encodings and corpus sections a bill actually amends. This view
-- computes that server-side from diffs and returns only the small result,
-- so the wire payload is tiny. The frontend queries it filtered by bill id
-- (?id=in.(...)) for just the rows on screen, so the jsonb work is bounded
-- to <=500 rows and uses the bills primary key.
--
-- "matched" mirrors the client logic that used to run over raw diffs:
--   * an encoding is matched only if a diff section references it AND has
--     at least one APPLIED amendment op (a mere citation doesn't count);
--   * a corpus section is matched only if it's in_corpus, has a
--     citation_path, and has at least one applied op.

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
      and jsonb_typeof(sec->'applied_ops') = 'array'
      and jsonb_array_length(sec->'applied_ops') > 0
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
      and jsonb_typeof(sec->'applied_ops') = 'array'
      and jsonb_array_length(sec->'applied_ops') > 0
  ) s
) cor on true;

grant select on bills.bill_list_summary to anon, authenticated, service_role;
