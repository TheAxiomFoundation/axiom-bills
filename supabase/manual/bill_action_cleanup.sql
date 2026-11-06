-- Reduce bills.bill_actions to one row per action.
--
-- Every refresh until the fix stored another copy of every action, under a
-- fingerprint no later run could match. This file defines the steps that remove
-- the copies. Installing it changes no data. bill_action_cleanup.py runs the
-- steps in order and prints where they stand: see that file for the commands.
--
-- It builds a new table and swaps it in, because it can't delete in place:
-- - A DELETE of 98% of the rows would write most of the table to the WAL and
--   leave the table at its full size on disk.
-- - One big sort needs about 28 GB of temporary space, and the disk has 6.6 GiB
--   free.
--
-- The steps:
--
--   prepare    Refuses all writes to the old table and drops its unique index on
--              (bill_id, fingerprint). That frees 17 GB, so the build stays well
--              under the 90% line where Supabase grows the disk for good. The
--              bill page reads through idx_actions_bill_occurred, so reads carry
--              on as they are. Creates the new table in this file's own schema,
--              where no API role can reach it.
--   copy       Reads the old table in heap order, a few thousand pages at a time,
--              and adds each action the new table doesn't hold yet. Each batch
--              commits with its place in the ledger, so a stop loses nothing and
--              a rerun picks up where it stopped.
--   build      Adds the remaining indexes and the foreign key to the new table,
--              one short statement each.
--   verify     Reads the old table again and confirms every row has its action
--              in the new table, by bill, moment and text, not by fingerprint.
--   swap       Checks that the new table matches the old one's columns,
--              constraints, indexes, policies and grants, then moves the old
--              table out of the bills schema and the new one in, in one short
--              transaction. Reads see the old table until the commit and the new
--              one after it.
--   finish     Drops the old table and these schemas. Only this step can't be
--              undone from here. Run it once the bill pages look right, about a
--              week later.
--
-- What each kept row holds:
-- - Its action: bill, moment and text. An action's copies share these.
-- - ingested_at: the earliest copy's, so it still says when we first stored it.
-- - chamber, normalized_status, source_url: the last stored copy's. Where copies
--   differ, it's because a later scraper fixed them. The next scrape corrects
--   any row where heap order and ingest order disagree.
-- - fingerprint: the current scheme's, which the sync computes the same way.
--
-- Maryland also dated its current status and "Passed by the General Assembly"
-- with the time the state wrote its feed, so those rows hold a new date each run.
-- They collapse by bill and text to the earliest date. In us-md, a row whose time
-- has nonzero seconds is one of these: the feed's real milestones carry dates and
-- whole minutes, and the feed's snapshot times carry fractions of a second. A
-- snapshot time that fell exactly on a minute would stay as a row of its own, and
-- the sample holds none.
--
-- To reverse:
-- - Before swap: bill_action_cleanup.py abort drops the new table and removes the
--   write block. The old table then needs its unique index back before any sync
--   can write: abort prints the statements. They take hours and a direct
--   connection, and at that table's size the sort can cross the 90% line, which
--   grows the disk for good.
-- - After swap, before finish: bill_action_cleanup.py swap-back puts the old table
--   back, and anything written since the swap stays with the new table. Then abort,
--   as above. The old table refuses writes until then.
-- - After finish: restore a daily backup of the whole project.

begin;
set local lock_timeout = '5s';

create schema if not exists bill_action_cleanup;
revoke all on schema bill_action_cleanup from public;
-- A separate schema, so both tables keep their own names and their indexes' names
-- through the swap, and the swap needs no renames.
create schema if not exists bill_action_cleanup_old;
revoke all on schema bill_action_cleanup_old from public;

create table if not exists bill_action_cleanup.state (
  only_row boolean primary key default true check (only_row),
  heap_pages bigint not null,
  prepared_at timestamptz not null default now(),
  built_at timestamptz,
  swapped_at timestamptz
);

create table if not exists bill_action_cleanup.copied (
  first_page bigint primary key,
  next_page bigint not null,
  rows_read bigint not null,
  actions_read bigint not null,
  rows_added bigint not null,
  rows_changed bigint not null,
  undated_rows bigint not null,
  undated_on_whole_seconds bigint not null,
  done_at timestamptz not null default now()
);

create table if not exists bill_action_cleanup.verified (
  first_page bigint primary key,
  next_page bigint not null,
  rows_read bigint not null,
  rows_missing bigint not null,
  done_at timestamptz not null default now()
);

create table if not exists bill_action_cleanup.undated_bills (bill_id uuid primary key);

-- db.action_fingerprint in SQL. test_bill_action_cleanup.py holds the two together.
create or replace function bill_action_cleanup.action_fingerprint(
  occurred_at timestamptz, action_text text, undated boolean
) returns text
language sql stable parallel safe as $$
  select case when undated
    then 'u1:' || encode(sha256(convert_to(action_text, 'UTF8')), 'hex')
    else 'a1:' || encode(sha256(convert_to(
      to_char(occurred_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US')
        || E'\n' || action_text, 'UTF8')), 'hex')
  end
$$;

create or replace function bill_action_cleanup.refuse_write() returns trigger
language plpgsql as $$
begin
  raise exception 'bills.bill_actions is frozen for the cleanup in supabase/manual/bill_action_cleanup.sql';
end
$$;

-- Where the steps stand.
create or replace function bill_action_cleanup.status() returns jsonb
language sql stable as $$
  select jsonb_build_object(
    'prepared', exists (select from bill_action_cleanup.state),
    'heap_pages', (select heap_pages from bill_action_cleanup.state),
    'copied_through', (select coalesce(max(next_page), 0) from bill_action_cleanup.copied),
    'rows_read', (select coalesce(sum(rows_read), 0) from bill_action_cleanup.copied),
    'rows_kept', (select coalesce(sum(rows_added), 0) from bill_action_cleanup.copied),
    'rows_changed', (select coalesce(sum(rows_changed), 0) from bill_action_cleanup.copied),
    'undated_rows', (select coalesce(sum(undated_rows), 0) from bill_action_cleanup.copied),
    'undated_on_whole_seconds', (select coalesce(sum(undated_on_whole_seconds), 0) from bill_action_cleanup.copied),
    'built', (select built_at is not null from bill_action_cleanup.state),
    'verified_through', (select coalesce(max(next_page), 0) from bill_action_cleanup.verified),
    'rows_verified', (select coalesce(sum(rows_read), 0) from bill_action_cleanup.verified),
    'rows_missing', (select coalesce(sum(rows_missing), 0) from bill_action_cleanup.verified),
    'swapped', (select swapped_at is not null from bill_action_cleanup.state)
  )
$$;

create or replace function bill_action_cleanup.prepare() returns jsonb
language plpgsql as $$
declare
  acl record;
  policy record;
begin
  perform set_config('lock_timeout', '5s', true);
  if exists (select from bill_action_cleanup.state) then
    raise exception 'prepare already ran';
  end if;
  if to_regclass('bills.bill_actions_event_key') is not null then
    raise exception 'bills.bill_actions already has its event key, so it holds no copies';
  end if;

  execute 'create trigger bill_actions_frozen before insert or update or delete on bills.bill_actions
           for each statement execute function bill_action_cleanup.refuse_write()';
  execute 'create trigger bill_actions_frozen_truncate before truncate on bills.bill_actions
           for each statement execute function bill_action_cleanup.refuse_write()';
  alter table bills.bill_actions drop constraint if exists bill_actions_bill_id_fingerprint_key;

  insert into bill_action_cleanup.undated_bills
    select id from bills.bills where jurisdiction = 'us-md';

  create table bill_action_cleanup.bill_actions (
    like bills.bill_actions
      including defaults including constraints including storage including comments
  );
  alter table bill_action_cleanup.bill_actions
    add constraint bill_actions_bill_id_fingerprint_key unique (bill_id, fingerprint);

  for acl in
    select r.rolname, a.privilege_type
      from pg_class c
      cross join lateral aclexplode(c.relacl) a
      join pg_roles r on r.oid = a.grantee
     where c.oid = 'bills.bill_actions'::regclass and a.grantee <> c.relowner
  loop
    execute format('grant %s on bill_action_cleanup.bill_actions to %I', acl.privilege_type, acl.rolname);
  end loop;

  for policy in
    select * from pg_policies where schemaname = 'bills' and tablename = 'bill_actions'
  loop
    execute format(
      'create policy %I on bill_action_cleanup.bill_actions as %s for %s to %s using (%s)',
      policy.policyname, policy.permissive, policy.cmd,
      (select string_agg(quote_ident(role_name), ', ') from unnest(policy.roles) as role_name),
      policy.qual
    );
  end loop;
  if (select relrowsecurity from pg_class where oid = 'bills.bill_actions'::regclass) then
    alter table bill_action_cleanup.bill_actions enable row level security;
  end if;

  insert into bill_action_cleanup.state (heap_pages)
    values (pg_relation_size('bills.bill_actions') / current_setting('block_size')::bigint);
  return bill_action_cleanup.status();
end
$$;

-- One batch of the copy. The joins probe the unique index row by row. Hash and
-- merge joins would read the whole new table for each batch, and Postgres can't
-- tell how small a batch is from its statistics.
create or replace function bill_action_cleanup.copy_batch(first_page bigint, next_page bigint)
returns jsonb
language plpgsql
set work_mem = '32MB'
set enable_hashjoin = off
set enable_mergejoin = off
set enable_seqscan = off
set enable_bitmapscan = off
as $$
begin
  if not exists (select from bill_action_cleanup.state) then
    raise exception 'run prepare first';
  end if;
  if (select built_at from bill_action_cleanup.state) is not null then
    raise exception 'build already ran, so the copy is finished';
  end if;
  if first_page <> (select coalesce(max(c.next_page), 0) from bill_action_cleanup.copied c) then
    raise exception 'copy_batch(%, %) is out of order', first_page, next_page;
  end if;

  with raw as materialized (
    select a.id, a.bill_id, a.occurred_at, a.chamber, a.action_text,
           a.normalized_status, a.source_url, a.ingested_at, a.ctid as place,
           extract(second from a.occurred_at at time zone 'UTC') <> 0
             and a.bill_id in (select u.bill_id from bill_action_cleanup.undated_bills u) as undated
      from bills.bill_actions a
     where a.ctid >= format('(%s,0)', first_page)::tid
       and a.ctid < format('(%s,0)', next_page)::tid
  ), identified as (
    select r.*, bill_action_cleanup.action_fingerprint(r.occurred_at, r.action_text, r.undated) as fingerprint
      from raw r
  ), actions as materialized (
    -- One row per action in this batch: the last stored copy, with the earliest
    -- dates among the batch's copies.
    select distinct on (i.bill_id, i.fingerprint)
           i.id, i.bill_id, i.chamber, i.action_text, i.normalized_status, i.source_url, i.fingerprint,
           min(i.occurred_at) over same_action as first_occurred,
           min(i.ingested_at) over same_action as first_ingested
      from identified i
    window same_action as (partition by i.bill_id, i.fingerprint)
     order by i.bill_id, i.fingerprint, i.ingested_at desc, i.place desc
  ), matched as materialized (
    select a.*, s.ctid as stored_place, s.occurred_at as stored_occurred, s.ingested_at as stored_ingested,
           s.chamber as stored_chamber, s.normalized_status as stored_status, s.source_url as stored_url
      from actions a
      left join bill_action_cleanup.bill_actions s
        on s.bill_id = a.bill_id and s.fingerprint = a.fingerprint
  ), added as (
    insert into bill_action_cleanup.bill_actions
      (id, bill_id, occurred_at, chamber, action_text, normalized_status, source_url, fingerprint, ingested_at)
    select m.id, m.bill_id, m.first_occurred, m.chamber, m.action_text, m.normalized_status,
           m.source_url, m.fingerprint, m.first_ingested
      from matched m
     where m.stored_place is null
    returning 1
  ), changed as (
    update bill_action_cleanup.bill_actions s
       set chamber = m.chamber,
           normalized_status = m.normalized_status,
           source_url = m.source_url,
           occurred_at = least(m.stored_occurred, m.first_occurred),
           ingested_at = least(m.stored_ingested, m.first_ingested)
      from matched m
     where m.stored_place is not null
       and (m.chamber is distinct from m.stored_chamber
            or m.normalized_status is distinct from m.stored_status
            or m.source_url is distinct from m.stored_url
            or m.first_occurred < m.stored_occurred
            or m.first_ingested < m.stored_ingested)
       and s.ctid = m.stored_place
    returning 1
  )
  insert into bill_action_cleanup.copied
    (first_page, next_page, rows_read, actions_read, rows_added, rows_changed, undated_rows, undated_on_whole_seconds)
  select copy_batch.first_page, copy_batch.next_page,
         (select count(*) from raw),
         (select count(*) from actions),
         (select count(*) from added),
         (select count(*) from changed),
         (select count(*) from raw r where r.undated),
         (select count(*) from raw r where r.undated and r.occurred_at = date_trunc('second', r.occurred_at));

  return bill_action_cleanup.status();
end
$$;

-- Adds one missing piece to the new table and says which. The driver calls it until
-- it returns null. The Management API stops a statement after 2 minutes, so each
-- piece gets its own, and a rerun skips what's there.
create or replace function bill_action_cleanup.build_next() returns text
language plpgsql as $$
declare
  through bigint;
  pages bigint;
begin
  select heap_pages into pages from bill_action_cleanup.state;
  select coalesce(max(next_page), 0) into through from bill_action_cleanup.copied;
  if pages is null or through < pages then
    raise exception 'the copy reached page % of %', through, pages;
  end if;
  if (select built_at from bill_action_cleanup.state) is not null then
    return null;
  end if;

  if not exists (select from pg_constraint
                  where conrelid = 'bill_action_cleanup.bill_actions'::regclass
                    and conname = 'bill_actions_pkey') then
    alter table bill_action_cleanup.bill_actions add constraint bill_actions_pkey primary key (id);
    return 'bill_actions_pkey';
  end if;
  if to_regclass('bill_action_cleanup.idx_actions_bill_occurred') is null then
    create index idx_actions_bill_occurred on bill_action_cleanup.bill_actions (bill_id, occurred_at desc);
    return 'idx_actions_bill_occurred';
  end if;
  if to_regclass('bill_action_cleanup.bill_actions_event_key') is null then
    create unique index bill_actions_event_key on bill_action_cleanup.bill_actions
      (bill_id, occurred_at, md5(action_text));
    return 'bill_actions_event_key';
  end if;
  if not exists (select from pg_constraint
                  where conrelid = 'bill_action_cleanup.bill_actions'::regclass
                    and conname = 'bill_actions_bill_id_fkey') then
    alter table bill_action_cleanup.bill_actions
      add constraint bill_actions_bill_id_fkey foreign key (bill_id) references bills.bills (id) on delete cascade;
    return 'bill_actions_bill_id_fkey';
  end if;
  analyze bill_action_cleanup.bill_actions;
  update bill_action_cleanup.state set built_at = now();
  return 'statistics';
end
$$;

-- One batch of the check. It reads the old table again and looks each row's action
-- up by bill, moment and text, so it doesn't lean on the fingerprint the copy used.
create or replace function bill_action_cleanup.verify_batch(first_page bigint, next_page bigint)
returns jsonb
language plpgsql
set work_mem = '32MB'
set enable_hashjoin = off
set enable_mergejoin = off
set enable_seqscan = off
set enable_bitmapscan = off
as $$
begin
  if (select built_at from bill_action_cleanup.state) is null then
    raise exception 'run build first';
  end if;
  if first_page <> (select coalesce(max(v.next_page), 0) from bill_action_cleanup.verified v) then
    raise exception 'verify_batch(%, %) is out of order', first_page, next_page;
  end if;

  with raw as materialized (
    select a.bill_id, a.occurred_at, a.action_text,
           extract(second from a.occurred_at at time zone 'UTC') <> 0
             and a.bill_id in (select u.bill_id from bill_action_cleanup.undated_bills u) as undated
      from bills.bill_actions a
     where a.ctid >= format('(%s,0)', first_page)::tid
       and a.ctid < format('(%s,0)', next_page)::tid
  )
  insert into bill_action_cleanup.verified (first_page, next_page, rows_read, rows_missing)
  select verify_batch.first_page, verify_batch.next_page, count(*),
         count(*) filter (where not case
           when r.undated then exists (
             select from bill_action_cleanup.bill_actions s
              where s.bill_id = r.bill_id and s.occurred_at <= r.occurred_at
                and s.action_text = r.action_text)
           else exists (
             select from bill_action_cleanup.bill_actions s
              where s.bill_id = r.bill_id and s.occurred_at = r.occurred_at
                and md5(s.action_text) = md5(r.action_text) and s.action_text = r.action_text)
         end)
    from raw r;

  return bill_action_cleanup.status();
end
$$;

-- Everything that stands between the new table and the swap. Empty means go.
create or replace function bill_action_cleanup.problems() returns text[]
language plpgsql stable as $$
declare
  found text[] := '{}';
  pages bigint;
  extra text;
  old_table constant oid := 'bills.bill_actions'::regclass;
  new_table constant oid := to_regclass('bill_action_cleanup.bill_actions');
begin
  if new_table is null then
    return array['the new table does not exist'];
  end if;
  select heap_pages into pages from bill_action_cleanup.state;
  if (select built_at from bill_action_cleanup.state) is null then
    found := found || 'build has not run'::text;
  end if;
  if not exists (select from pg_trigger
                  where tgrelid = old_table and tgname = 'bill_actions_frozen' and tgenabled <> 'D')
     or not exists (select from pg_trigger
                     where tgrelid = old_table and tgname = 'bill_actions_frozen_truncate' and tgenabled <> 'D') then
    found := found || 'the old table no longer refuses writes, so it may hold rows the copy never read'::text;
  end if;
  if pg_relation_size(old_table) / current_setting('block_size')::bigint <> pages then
    found := found || 'the old table changed size since prepare, so it may hold rows the copy never read'::text;
  end if;
  if (select coalesce(max(next_page), 0) from bill_action_cleanup.copied) < pages then
    found := found || 'the copy has not reached the last page'::text;
  end if;
  if (select coalesce(max(next_page), 0) from bill_action_cleanup.verified) < pages then
    found := found || 'verify has not reached the last page'::text;
  end if;
  if (select coalesce(sum(rows_missing), 0) from bill_action_cleanup.verified) > 0 then
    found := found || format('verify found %s rows with no action in the new table',
                             (select sum(rows_missing) from bill_action_cleanup.verified));
  end if;
  if (select coalesce(sum(rows_read), 0) from bill_action_cleanup.copied)
     <> (select coalesce(sum(rows_read), 0) from bill_action_cleanup.verified) then
    found := found || 'the copy and verify read different numbers of rows'::text;
  end if;
  if (select coalesce(sum(rows_added), 0) from bill_action_cleanup.copied)
     <> (select count(*) from bill_action_cleanup.bill_actions) then
    found := found || 'the new table holds a different number of rows from the ones the copy added'::text;
  end if;
  if exists (select from bill_action_cleanup.bill_actions
              where fingerprint !~ '^(a1|u1):[0-9a-f]{64}$') then
    found := found || 'the new table holds a fingerprint outside the current schemes'::text;
  end if;

  -- Moving the table leaves anything that depends on it pointing at the old one.
  select string_agg(distinct r.ev_class::regclass::text, ', ') into extra
    from pg_depend d
    join pg_rewrite r on r.oid = d.objid
   where d.refobjid = old_table and d.refclassid = 'pg_class'::regclass
     and d.classid = 'pg_rewrite'::regclass and r.ev_class <> old_table;
  if extra is not null then
    found := found || format('views depend on the old table: %s', extra);
  end if;
  select string_agg(c.conrelid::regclass::text, ', ') into extra
    from pg_constraint c where c.confrelid = old_table;
  if extra is not null then
    found := found || format('foreign keys reference the old table: %s', extra);
  end if;

  -- The columns: same names, order, types, nullability and defaults.
  select string_agg(x, '; ') into extra from (
    select coalesce(o.c, n.c) as x from (
      select a.attnum, a.attname || ' ' || format_type(a.atttypid, a.atttypmod)
               || case when a.attnotnull then ' not null' else '' end
               || coalesce(' default ' || pg_get_expr(d.adbin, d.adrelid), '') as c
        from pg_attribute a left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
       where a.attrelid = old_table and a.attnum > 0 and not a.attisdropped
    ) o full join (
      select a.attnum, a.attname || ' ' || format_type(a.atttypid, a.atttypmod)
               || case when a.attnotnull then ' not null' else '' end
               || coalesce(' default ' || pg_get_expr(d.adbin, d.adrelid), '') as c
        from pg_attribute a left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
       where a.attrelid = new_table and a.attnum > 0 and not a.attisdropped
    ) n using (attnum)
    where o.c is distinct from n.c
  ) differing;
  if extra is not null then
    found := found || format('columns differ: %s', extra);
  end if;

  -- The constraints: the new table holds every one of the old table's, plus the
  -- unique key prepare dropped from the old table, and nothing else.
  select string_agg(conname, ', ') into extra from (
    (select c.conname, pg_get_constraintdef(c.oid) from pg_constraint c where c.conrelid = old_table)
    except
    (select c.conname, pg_get_constraintdef(c.oid) from pg_constraint c where c.conrelid = new_table)
  ) missing;
  if extra is not null then
    found := found || format('constraints missing from the new table: %s', extra);
  end if;
  select string_agg(conname, ', ') into extra from (
    (select c.conname from pg_constraint c where c.conrelid = new_table)
    except
    (select c.conname from pg_constraint c where c.conrelid = old_table)
    except
    (select 'bill_actions_bill_id_fingerprint_key'::name)
  ) surplus;
  if extra is not null then
    found := found || format('constraints only on the new table: %s', extra);
  end if;

  -- The indexes, the same way, plus the event key.
  select string_agg(def, ', ') into extra from (
    (select replace(pg_get_indexdef(i.indexrelid), ' ON bills.bill_actions ', ' ON t ') as def
       from pg_index i where i.indrelid = old_table)
    except
    (select replace(pg_get_indexdef(i.indexrelid), ' ON bill_action_cleanup.bill_actions ', ' ON t ')
       from pg_index i where i.indrelid = new_table)
  ) missing;
  if extra is not null then
    found := found || format('indexes missing from the new table: %s', extra);
  end if;
  select string_agg(relname, ', ') into extra from (
    (select c.relname from pg_index i join pg_class c on c.oid = i.indexrelid where i.indrelid = new_table)
    except
    (select c.relname from pg_index i join pg_class c on c.oid = i.indexrelid where i.indrelid = old_table)
    except
    (select unnest(array['bill_actions_bill_id_fingerprint_key', 'bill_actions_event_key']::name[]))
  ) surplus;
  if extra is not null then
    found := found || format('indexes only on the new table: %s', extra);
  end if;

  -- Who can read it, and through what.
  if (select (relrowsecurity, relforcerowsecurity, coalesce(reloptions, '{}')) from pg_class where oid = old_table)
     is distinct from
     (select (relrowsecurity, relforcerowsecurity, coalesce(reloptions, '{}')) from pg_class where oid = new_table) then
    found := found || 'row-level security or storage options differ'::text;
  end if;
  if (select array_agg(item::text order by item::text) from pg_class c, unnest(c.relacl) item where c.oid = old_table)
     is distinct from
     (select array_agg(item::text order by item::text) from pg_class c, unnest(c.relacl) item where c.oid = new_table) then
    found := found || 'grants differ'::text;
  end if;
  if (select array_agg((policyname, permissive, roles, cmd, qual, with_check)::text order by policyname)
        from pg_policies where schemaname = 'bills' and tablename = 'bill_actions')
     is distinct from
     (select array_agg((policyname, permissive, roles, cmd, qual, with_check)::text order by policyname)
        from pg_policies where schemaname = 'bill_action_cleanup' and tablename = 'bill_actions') then
    found := found || 'policies differ'::text;
  end if;
  return found;
end
$$;

create or replace function bill_action_cleanup.swap() returns jsonb
language plpgsql as $$
declare
  found text[];
begin
  perform set_config('lock_timeout', '2s', true);
  if (select swapped_at from bill_action_cleanup.state) is not null then
    raise exception 'swap already ran';
  end if;
  found := bill_action_cleanup.problems();
  if cardinality(found) > 0 then
    raise exception 'not swapping: %', array_to_string(found, '; ');
  end if;
  alter table bills.bill_actions set schema bill_action_cleanup_old;
  alter table bill_action_cleanup.bill_actions set schema bills;
  update bill_action_cleanup.state set swapped_at = now();
  notify pgrst, 'reload schema';
  return bill_action_cleanup.status();
end
$$;

create or replace function bill_action_cleanup.swap_back() returns jsonb
language plpgsql as $$
begin
  perform set_config('lock_timeout', '2s', true);
  if (select swapped_at from bill_action_cleanup.state) is null then
    raise exception 'swap has not run';
  end if;
  if to_regclass('bill_action_cleanup_old.bill_actions') is null then
    raise exception 'finish already dropped the old table';
  end if;
  alter table bills.bill_actions set schema bill_action_cleanup;
  alter table bill_action_cleanup_old.bill_actions set schema bills;
  update bill_action_cleanup.state set swapped_at = null;
  notify pgrst, 'reload schema';
  return bill_action_cleanup.status();
end
$$;

-- Stops before the swap, or after swap_back: drops the new table and lifts the write
-- block, and leaves the old table without its unique index. Rebuilding that index
-- takes hours, so the driver prints the statements for a direct connection.
create or replace function bill_action_cleanup.abort() returns jsonb
language plpgsql as $$
begin
  perform set_config('lock_timeout', '5s', true);
  if (select swapped_at from bill_action_cleanup.state) is not null then
    raise exception 'swap already ran: use swap-back';
  end if;
  drop table if exists bill_action_cleanup.bill_actions;
  drop trigger if exists bill_actions_frozen on bills.bill_actions;
  drop trigger if exists bill_actions_frozen_truncate on bills.bill_actions;
  delete from bill_action_cleanup.copied;
  delete from bill_action_cleanup.verified;
  delete from bill_action_cleanup.undated_bills;
  delete from bill_action_cleanup.state;
  return bill_action_cleanup.status();
end
$$;

-- The one step this file can't undo.
create or replace function bill_action_cleanup.finish() returns jsonb
language plpgsql as $$
declare
  kept bigint;
begin
  perform set_config('lock_timeout', '5s', true);
  if (select swapped_at from bill_action_cleanup.state) is null then
    raise exception 'swap has not run';
  end if;
  kept := (select count(*) from bills.bill_actions);
  drop table if exists bill_action_cleanup_old.bill_actions;
  drop schema if exists bill_action_cleanup_old;
  return jsonb_build_object('rows_now', kept);
end
$$;

commit;
