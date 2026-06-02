# axiom-bills

Live bill tracking for federal and state legislatures, feeding the Axiom
encoding pipeline. Not a wrapper around OpenStates or LegiScan — pulls
directly from authoritative sources (Congress.gov, state legislatures).

## Layout

```
axiom-bills/
  packages/
    scrapers/      # Python. Per-jurisdiction bill scrapers + writer.
    api/           # FastAPI read API.
    web/           # Vite + React frontend (jurisdiction-first).
  db/
    migrations/    # Plain .sql files, applied in order.
    axiom_bills.sqlite   # created by `make migrate`
```

## Jurisdictions in the prototype

| Code    | Source                        | Status      |
|---------|-------------------------------|-------------|
| `us`    | Congress.gov API              | Full impl   |
| `us-ny` | legislation.nysenate.gov API  | Full impl   |
| `us-co` | leg.colorado.gov              | Full impl   |
| `us-de` | legis.delaware.gov JSON feeds | Full impl   |
| `us-ks` | Kansas KLISS REST API         | Full impl   |
| `us-md` | mgaleg.maryland.gov JSON data | Full impl   |
| `us-mn` | revisor.mn.gov                | Full impl   |
| `us-or` | Oregon OLIS OData API         | Full impl   |

## Quickstart (no Docker, SQLite under the hood)

```bash
# 1. Install scrapers + API
cd packages/scrapers && uv sync --extra dev
cd ../api && uv sync

# 2. Install frontend
cd ../web && npm install
cd ../..

# 3. Create the DB
make migrate

# 4. Free API keys
export CONGRESS_API_KEY=...   # https://api.congress.gov/sign-up/
export NYSENATE_API_KEY=...   # https://legislation.nysenate.gov/

# 5. Pull some bills (~30 sec each)
make scrape-federal
make scrape-ny
make scrape-co
make scrape-de
make scrape-ks
make scrape-md
make scrape-mn
make scrape-or

# 6. Two terminals:
make api    # http://127.0.0.1:8000  (docs at /docs)
make web    # http://127.0.0.1:5180
```

You can also open `db/axiom_bills.sqlite` in any SQLite browser to poke
at the data directly.

## Deploy (Supabase + Vercel)

End state: the frontend at `packages/web/` reads directly from a
Supabase Postgres project; no API service runs in production. Diffs
are precomputed and stored in `bills.bills.diffs` (JSONB).

```bash
# 1. Create a Supabase project (call it axiom-bills). Apply migrations:
#    Studio → SQL Editor → paste supabase/migrations/*.sql, run.
#    Then in API settings, add `bills` to "Exposed schemas".

# 2. From the project's Settings → API page, grab:
#      Project URL              → SUPABASE_URL
#      anon public key          → SUPABASE_ANON_KEY (frontend)
#      service_role secret key  → SUPABASE_SERVICE_KEY (sync only)

# 3. Push local SQLite → Supabase (idempotent; safe to re-run):
export SUPABASE_URL=https://<project>.supabase.co
export SUPABASE_SERVICE_KEY=eyJ...           # service_role
cd packages/scrapers
.venv/bin/python -m axiom_bills.cli precompute-diffs   # fills bills.diffs
.venv/bin/python -m axiom_bills.cli sync-supabase      # uploads to PG

# 4. Frontend env:
cd ../web
cp .env.example .env.local
#   VITE_SUPABASE_URL=...     # same URL
#   VITE_SUPABASE_ANON_KEY=...# anon key
npm run dev                                  # http://127.0.0.1:5180

# 5. Vercel:
#    - New project pointing at packages/web/
#    - vercel.json (already committed) declares the Vite framework
#    - Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in env vars
#    - Push to main → Vercel deploys automatically
```

The FastAPI service in `packages/api/` is kept for local development
convenience (the dev proxy was removed). Production no longer runs it.

## How a scrape works

```
RateLimitedClient  → Congress.gov / NYSenate JSON
        ↓
  Bill / BillAction / BillVersion  (pydantic)
        ↓
  axiom_bills._common.db.write()
        ↓
  SQLite: bills (upsert), bill_actions (append-only by fingerprint),
          bill_versions, scrape_runs
        ↓
  _refresh_current_status() rolls up actions → bills.current_status
  using STATUS_ORDER so out-of-order actions can't unwind progress.
```

The status-text → normalized-status map lives per-jurisdiction in
`jurisdictions/<code>/bill/status.py`, covered by
`tests/test_status_patterns.py` (24 patterns currently green).

## Why not OpenStates

OpenStates is a great normalizer but: (a) free-tier rate limits make
full 50-state coverage painful, (b) topic-search is keyword-driven so
novel policy areas miss, (c) we want to own the status-normalization
mapping per state — that's what determines when Pipeline B fires the
"enactment" signal into the encoding stack.

## Status

Prototype. Federal + NY work end-to-end. CO + MN have status
vocabularies done and tested but their `scrape()` methods return empty
results. Schema and scraper base class are stable enough that adding a
5th jurisdiction is a single-file change.

For background on where this slots into the broader Axiom auto-update
layer, see the design conversation in the architecture notes (Pipelines
A/B/C).
