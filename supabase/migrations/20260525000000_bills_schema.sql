-- axiom-bills: Postgres schema mirroring our local SQLite, ready for
-- Supabase. Matches the SQLite migrations in db/migrations/ in spirit
-- but uses Postgres-native types (uuid, jsonb, generated columns).
--
-- The frontend reads these tables directly via @supabase/supabase-js;
-- writes go through a service-role-key-authenticated sync command in
-- the scrapers package. Anon role gets SELECT on everything.

create schema if not exists bills;

-- Tighten the search path so subsequent CREATEs land in the bills schema.
set search_path to bills, public;

-- ────────────────────────────────────────────────────────────────────
-- Enums
-- ────────────────────────────────────────────────────────────────────

do $$
begin
  if not exists (select 1 from pg_type where typname = 'chamber') then
    create type bills.chamber as enum ('lower', 'upper', 'joint', 'executive');
  end if;
  if not exists (select 1 from pg_type where typname = 'normalized_status') then
    create type bills.normalized_status as enum (
      'introduced', 'in_committee', 'passed_chamber', 'passed_both',
      'enrolled', 'signed', 'enacted', 'vetoed', 'veto_overridden',
      'failed', 'unknown'
    );
  end if;
  if not exists (select 1 from pg_type where typname = 'bill_kind') then
    create type bills.bill_kind as enum (
      'substantive', 'placeholder', 'ceremonial', 'appropriations',
      'procedural', 'vehicle', 'unknown'
    );
  end if;
  if not exists (select 1 from pg_type where typname = 'coverage') then
    create type bills.coverage as enum ('full', 'stub', 'planned');
  end if;
end $$;

-- ────────────────────────────────────────────────────────────────────
-- Tables
-- ────────────────────────────────────────────────────────────────────

create table if not exists bills.jurisdictions (
  code            text primary key,
  name            text not null,
  level           text not null check (level in ('federal', 'state')),
  source_url      text not null,
  coverage        bills.coverage not null default 'planned',
  created_at      timestamptz not null default now()
);

create table if not exists bills.sessions (
  id              uuid primary key default gen_random_uuid(),
  jurisdiction    text not null references bills.jurisdictions(code),
  name            text not null,
  start_date      date,
  end_date        date,
  is_current      boolean not null default false,
  unique (jurisdiction, name)
);
create index if not exists idx_sessions_current
  on bills.sessions(jurisdiction) where is_current;

create table if not exists bills.bills (
  id                  uuid primary key default gen_random_uuid(),
  jurisdiction        text not null references bills.jurisdictions(code),
  session_id          uuid not null references bills.sessions(id) on delete cascade,
  chamber             bills.chamber not null,
  number              text not null,
  title               text,
  summary             text,
  subjects            text[] not null default '{}',
  sponsors            jsonb not null default '[]'::jsonb,
  source_url          text not null,
  current_status      bills.normalized_status not null default 'unknown',
  current_status_at   timestamptz,
  kind                bills.bill_kind not null default 'substantive',
  first_seen_at       timestamptz not null default now(),
  last_scraped_at     timestamptz not null default now(),
  -- Pre-computed bill diff payload — written by the precompute-diffs
  -- command. Frontend reads this directly instead of computing on the fly.
  diffs               jsonb,
  unique (jurisdiction, session_id, chamber, number)
);
create index if not exists idx_bills_jurisdiction_status on bills.bills(jurisdiction, current_status);
create index if not exists idx_bills_status_at on bills.bills(current_status_at desc nulls last);
create index if not exists idx_bills_kind on bills.bills(jurisdiction, kind);
create index if not exists idx_bills_subjects on bills.bills using gin(subjects);

create table if not exists bills.bill_actions (
  id                 uuid primary key default gen_random_uuid(),
  bill_id            uuid not null references bills.bills(id) on delete cascade,
  occurred_at        timestamptz not null,
  chamber            bills.chamber,
  action_text        text not null,
  normalized_status  bills.normalized_status,
  source_url         text,
  fingerprint        text not null,
  ingested_at        timestamptz not null default now(),
  unique (bill_id, fingerprint)
);
create index if not exists idx_actions_bill_occurred on bills.bill_actions(bill_id, occurred_at desc);

create table if not exists bills.bill_versions (
  id            uuid primary key default gen_random_uuid(),
  bill_id       uuid not null references bills.bills(id) on delete cascade,
  label         text not null,
  source_url    text not null,
  format        text not null,
  text_sha256   text,
  fetched_at    timestamptz,
  unique (bill_id, label)
);

create table if not exists bills.bill_texts (
  id              uuid primary key default gen_random_uuid(),
  bill_id         uuid not null references bills.bills(id) on delete cascade,
  version_label   text not null,
  source_url      text not null,
  format          text not null,
  text            text not null,
  text_sha256     text not null,
  fetched_at      timestamptz not null default now(),
  unique (bill_id, version_label)
);

create table if not exists bills.bill_citations (
  id              uuid primary key default gen_random_uuid(),
  bill_id         uuid not null references bills.bills(id) on delete cascade,
  raw             text not null,
  citation        text not null,
  source          text not null check (source in ('title','summary','text','action')),
  extracted_at    timestamptz not null default now(),
  unique (bill_id, citation, source)
);
create index if not exists idx_bill_citations_bill on bills.bill_citations(bill_id);
create index if not exists idx_bill_citations_citation on bills.bill_citations(citation);

create table if not exists bills.axiom_encodings (
  id              uuid primary key default gen_random_uuid(),
  jurisdiction    text not null,
  repo            text not null,
  kind            text not null check (kind in ('statute', 'regulation', 'policy')),
  citation        text not null,
  file_path       text not null unique,
  indexed_at      timestamptz not null default now()
);
create index if not exists idx_encodings_citation on bills.axiom_encodings(citation);

create table if not exists bills.encoded_rules (
  id                          uuid primary key default gen_random_uuid(),
  encoding_id                 uuid not null references bills.axiom_encodings(id) on delete cascade,
  rule_name                   text not null,
  rule_kind                   text,
  rule_source                 text not null,
  rule_dtype                  text,
  module_corpus_citation_path text,
  indexed_at                  timestamptz not null default now()
);
create index if not exists idx_encoded_rules_source on bills.encoded_rules(rule_source);
create index if not exists idx_encoded_rules_encoding on bills.encoded_rules(encoding_id);

create table if not exists bills.encoded_rule_atoms (
  id                    uuid primary key default gen_random_uuid(),
  rule_id               uuid not null references bills.encoded_rules(id) on delete cascade,
  atom_path             text,
  atom_kind             text,
  corpus_citation_path  text,
  text                  text not null
);
create index if not exists idx_atoms_rule on bills.encoded_rule_atoms(rule_id);

-- ────────────────────────────────────────────────────────────────────
-- Anon read-access
-- ────────────────────────────────────────────────────────────────────
-- The frontend uses the anon key. Everything in this schema is public
-- reference data (it's all derived from public bill text + a public
-- corpus). Grants are SELECT-only; writes go through the service-role
-- key used by the scraper/sync commands.

grant usage on schema bills to anon, authenticated;
grant select on all tables in schema bills to anon, authenticated;
alter default privileges in schema bills
  grant select on tables to anon, authenticated;

-- Service role: full read/write — used by the scraper's sync command.
-- (Service role bypasses RLS but still needs explicit schema grants.)
grant usage on schema bills to service_role;
grant all on all tables in schema bills to service_role;
grant all on all sequences in schema bills to service_role;
alter default privileges in schema bills
  grant all on tables to service_role;
alter default privileges in schema bills
  grant all on sequences to service_role;

-- Seed jurisdictions. Same set as the local SQLite migration.
insert into bills.jurisdictions (code, name, level, source_url, coverage) values
  ('us',    'United States', 'federal', 'https://api.congress.gov',         'full'),
  ('us-ny', 'New York',      'state',   'https://legislation.nysenate.gov', 'full'),
  ('us-co', 'Colorado',      'state',   'https://leg.colorado.gov',         'stub'),
  ('us-mn', 'Minnesota',     'state',   'https://www.revisor.mn.gov',       'stub')
on conflict (code) do nothing;

-- The other 47 states + DC as 'planned'.
insert into bills.jurisdictions (code, name, level, source_url, coverage) values
  ('us-al','Alabama','state','https://alison.legislature.state.al.us','planned'),
  ('us-ak','Alaska','state','https://www.akleg.gov','planned'),
  ('us-az','Arizona','state','https://www.azleg.gov','planned'),
  ('us-ar','Arkansas','state','https://www.arkleg.state.ar.us','planned'),
  ('us-ca','California','state','https://leginfo.legislature.ca.gov','planned'),
  ('us-ct','Connecticut','state','https://www.cga.ct.gov','planned'),
  ('us-de','Delaware','state','https://legis.delaware.gov','planned'),
  ('us-fl','Florida','state','https://www.flsenate.gov','planned'),
  ('us-ga','Georgia','state','https://www.legis.ga.gov','planned'),
  ('us-hi','Hawaii','state','https://www.capitol.hawaii.gov','planned'),
  ('us-id','Idaho','state','https://legislature.idaho.gov','planned'),
  ('us-il','Illinois','state','https://www.ilga.gov','planned'),
  ('us-in','Indiana','state','https://iga.in.gov','planned'),
  ('us-ia','Iowa','state','https://www.legis.iowa.gov','planned'),
  ('us-ks','Kansas','state','https://kslegislature.org','planned'),
  ('us-ky','Kentucky','state','https://legislature.ky.gov','planned'),
  ('us-la','Louisiana','state','https://www.legis.la.gov','planned'),
  ('us-me','Maine','state','https://legislature.maine.gov','planned'),
  ('us-md','Maryland','state','https://mgaleg.maryland.gov','planned'),
  ('us-ma','Massachusetts','state','https://malegislature.gov','planned'),
  ('us-mi','Michigan','state','https://www.legislature.mi.gov','planned'),
  ('us-ms','Mississippi','state','http://billstatus.ls.state.ms.us','planned'),
  ('us-mo','Missouri','state','https://www.house.mo.gov','planned'),
  ('us-mt','Montana','state','https://leg.mt.gov','planned'),
  ('us-ne','Nebraska','state','https://nebraskalegislature.gov','planned'),
  ('us-nv','Nevada','state','https://www.leg.state.nv.us','planned'),
  ('us-nh','New Hampshire','state','https://gencourt.state.nh.us','planned'),
  ('us-nj','New Jersey','state','https://www.njleg.state.nj.us','planned'),
  ('us-nm','New Mexico','state','https://www.nmlegis.gov','planned'),
  ('us-nc','North Carolina','state','https://www.ncleg.gov','planned'),
  ('us-nd','North Dakota','state','https://www.legis.nd.gov','planned'),
  ('us-oh','Ohio','state','https://www.legislature.ohio.gov','planned'),
  ('us-ok','Oklahoma','state','https://www.oklegislature.gov','planned'),
  ('us-or','Oregon','state','https://olis.oregonlegislature.gov','planned'),
  ('us-pa','Pennsylvania','state','https://www.palegis.us','planned'),
  ('us-ri','Rhode Island','state','https://www.rilegislature.gov','planned'),
  ('us-sc','South Carolina','state','https://www.scstatehouse.gov','planned'),
  ('us-sd','South Dakota','state','https://sdlegislature.gov','planned'),
  ('us-tn','Tennessee','state','https://wapp.capitol.tn.gov','planned'),
  ('us-tx','Texas','state','https://capitol.texas.gov','planned'),
  ('us-ut','Utah','state','https://le.utah.gov','planned'),
  ('us-vt','Vermont','state','https://legislature.vermont.gov','planned'),
  ('us-va','Virginia','state','https://lis.virginia.gov','planned'),
  ('us-wa','Washington','state','https://app.leg.wa.gov','planned'),
  ('us-wv','West Virginia','state','https://www.wvlegislature.gov','planned'),
  ('us-wi','Wisconsin','state','https://docs.legis.wisconsin.gov','planned'),
  ('us-wy','Wyoming','state','https://wyoleg.gov','planned'),
  ('us-dc','District of Columbia','state','https://lims.dccouncil.gov','planned')
on conflict (code) do nothing;
