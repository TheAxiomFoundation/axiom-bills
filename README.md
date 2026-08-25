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

## Jurisdictions

The CLI registry (`axiom-bills list`) wires the federal scraper plus 51
state-level jurisdictions — all 50 states and DC — each with its own
scraper, status vocabulary, kind classifier, and citation extractor. A
sample of the sources (the registry in `cli.py` is authoritative):

| Code    | Source                        | Status      |
|---------|-------------------------------|-------------|
| `us`    | Congress.gov API              | Full impl   |
| `us-al` | alison.legislature.state.al.us official GraphQL | Full impl   |
| `us-ak` | akleg.gov BASIS               | Full impl   |
| `us-ny` | legislation.nysenate.gov API  | Full impl   |
| `us-co` | leg.colorado.gov              | Full impl   |
| `us-de` | legis.delaware.gov JSON feeds | Full impl   |
| `us-fl` | flsenate.gov                  | Full impl   |
| `us-id` | legislature.idaho.gov         | Full impl   |
| `us-ks` | Kansas KLISS REST API         | Full impl   |
| `us-ma` | malegislature.gov public API  | Full impl   |
| `us-md` | mgaleg.maryland.gov JSON data | Full impl   |
| `us-mn` | revisor.mn.gov                | Full impl   |
| `us-nc` | ncleg.gov official RSS feeds  | Full impl   |
| `us-nd` | ndlegis.gov official JSON API | Full impl   |
| `us-ne` | nebraskalegislature.gov       | Full impl   |
| `us-oh` | Ohio SOLAR/LIS API            | Full impl   |
| `us-or` | Oregon OLIS OData API         | Full impl   |
| `us-ri` | status.rilegislature.gov      | Full impl   |
| `us-sd` | sdlegislature.gov official API | Full impl   |
| `us-ut` | le.utah.gov official JSON     | Full impl   |
| `us-wi` | docs.legis.wisconsin.gov      | Full impl   |
| `us-wy` | wyoleg.gov official OData API | Full impl   |

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
make scrape-fl
make scrape-id
make scrape-ks
make scrape-md
make scrape-mn
make scrape-oh
make scrape-or
make scrape-sd
make scrape-ut
make scrape-wi

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
#    - Push to main → the Deploy web workflow ships to production
#      (.github/workflows/deploy-web.yml; needs the VERCEL_TOKEN secret)
```

Production deploys run from `.github/workflows/deploy-web.yml` on every
push to `main` that touches `packages/web/`. It needs one repo secret,
`VERCEL_TOKEN` (create at https://vercel.com/account/tokens). Until that
secret is set the workflow skips with a warning; deploy manually in the
meantime with `cd packages/web && vercel --prod`.

The FastAPI service in `packages/api/` is kept for local development
convenience (the dev proxy was removed). Production no longer runs it.

## The encoding loop (Pipeline B)

When a bill's amendment ops target a section that rulespec-us encodes,
the tracker computes a *rule variant*: the baseline YAML plus a patched
version reflecting the bill. Scalar substitutions patch automatically;
list/structural changes get an LLM-drafted proposal
(`propose-llm-variants`, needs `ANTHROPIC_API_KEY`).

```
index-encodings --repo ~/rulespec-us   # rulespec inventory → axiom_encodings
precompute-graph --repo ~/rulespec-us  # rulespec dependency graph → encoding_graphs
fetch-texts / precompute-diffs         # bill text → parsed ops (bills.diffs)
trigger-encodes -j us                  # staleness signals → encode_queue (enqueue-only)
precompute-variants                    # ops × encodings → rule_variants
hydrate-variants                       # reuse prior LLM proposals from Supabase
propose-llm-variants                   # draft the rest via Claude
hydrate-reconciliations                # reuse prior verdicts from Supabase
reconcile -j us                        # agentic bill↔encoding verdicts → bill_reconciliations
sync-supabase                          # push everything up
export-variants --out ./patches        # patched YAML + manifest for downstream
```

`fetch-texts` prefers HTML > XML > TXT > PDF; PDF text **is** fetched
(extracted via pypdf — scanned/encrypted PDFs are skipped).

`precompute-graph` snapshots the rulespec module dependency graph
(imports, proof-atom imports, formula references) that the web app's
Impact tab renders, with the bill's touched sections overlaid.

`reconcile` (needs `ANTHROPIC_API_KEY`) produces two enum-constrained
verdicts per touched section — billVsLaw (is the change substantive?)
and modelVsLaw (would the encoding be wrong post-enactment?) — that
drive the web app's triage view. `hydrate-reconciliations` runs first
in CI so unchanged sections reuse stored verdicts instead of
re-spending tokens.

The loop is *iterative*: each variant row stores a fingerprint of the
ops + baseline it was computed from (`source_ops_fingerprint`) and the
bill text hash (`source_text_sha256`). Re-running with unchanged inputs
is a no-op — LLM proposals survive. When an engrossed/enrolled text
changes the ops, the variant recomputes, the stale proposal is cleared
with a note, and the next `propose-llm-variants` re-drafts it.

The hourly federal refresh workflow runs the whole chain (it checks out
rulespec-us and indexes it each run). Downstream consumers read the
`bills.current_rule_patches` view in Supabase (latest patched YAML per
bill/file with bill status attached) or use `export-variants` locally.

## Closing the loop: the encode queue

`trigger-encodes` materializes the re-encode queue (`encode_queue`, one
row per bill × citation × reason) from three staleness signals:

- `needs_new_encoding` — a bill adds provisions inside an encoded
  program area that no rule file covers yet (encoder backlog);
- `stale_variant` — a bill's ops fingerprint changed and superseded a
  previously drafted LLM variant;
- `enacted_touch` — an enacted/signed bill amends an encoded file, so
  the baseline encoding itself is stale.

Rows are enqueue-once: a later scan never resurrects an existing row,
so a dismissed row stays dismissed. CI runs the enqueue-only scan
hourly; the pending count surfaces on the bill page ("N citations
queued for re-encode").

Running the queue is local and human-gated:

```bash
export AXIOM_CORPUS_PATH=~/axiom-corpus          # axiom-corpus clone
export AXIOM_POLICY_REPO_PATH=~/rulespec-us      # rulespec clone
export AXIOM_RULES_ENGINE_PATH=~/axiom-rules-engine
axiom-bills trigger-encodes -j us --run --limit 3
```

Each pending row shells out to `axiom-encode encode "<citation>" …`
(validate-only — never `--apply`; applying needs the signing supervisor)
with output under `$AXIOM_ENCODE_OUTPUT` or
`~/.axiom-bills/encode-runs/<queue-id>`, and records ran/failed plus the
exit code, output dir, and a stderr tail on the row.

**Manual prerequisite for enacted bills**: the encoder reads signed
axiom-corpus releases — it cannot consume bill text directly. The loop
for an enacted bill is: bill enacted → axiom-corpus ingests the amended
law text → a signed corpus release ships → the encode toolchain re-pins
to it → run the queue. Until the corpus catches up, an `enacted_touch`
run re-encodes against pre-enactment law and is only useful as a
baseline check.

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

Prototype, but broad: the registry wires federal plus all 51
state-level jurisdictions (50 states + DC), and the hourly federal
refresh runs the full encoding loop in CI. Schema and scraper base
class are stable enough that tuning a jurisdiction is a per-directory
change under `jurisdictions/<code>/`.

For background on where this slots into the broader Axiom auto-update
layer, see the design conversation in the architecture notes (Pipelines
A/B/C).
