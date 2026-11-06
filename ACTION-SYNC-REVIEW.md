# Stable action sync and production cleanup boundary

The cost investigation found 5,459 action rows but 29 distinct date/text events in a bounded five-bill sample. It does not establish a database-wide duplicate rate.

## Reproduced cause and fix

`db._fingerprint()` incorporates a random local bill ID. Remote sync maps that bill ID to the existing Supabase bill but previously retained the local fingerprint. A fresh SQLite database therefore bypasses the remote `(bill_id, fingerprint)` conflict key for the same event.

The sync boundary now identifies events by mapped bill ID, UTC-normalized occurrence timestamp and exact action text. It reuses a deterministic existing legacy row/fingerprint where available. New events receive a deterministic ID and fingerprint. Duplicate events in an outgoing batch collapse before upsert. Existing duplicate rows are not deleted; source text is not fuzzily matched or normalized. Local SQLite records are unchanged. This preserves the existing date/text notion of action identity.

## Rollout and verification

1. Review/merge the code fix through the normal deployment process. No deployment was performed from this branch.
2. Run a small normal ingestion twice, then repeat from a fresh local database. Compare retained distinct events and total remote rows: the second/third runs should add no rows for unchanged events. Retain query timing and request sizes.
3. Existing remote lookup still reads action rows by indexed bill IDs. Severe historical duplication can make that lookup expensive; measure representative batches before broad rollout. This patch does not claim to solve scan/pagination or concurrent-ingestion capacity. Run the canary without concurrent legacy writers.

## Cleanup plan — separate reviewed operation

- Verify a usable backup and perform a restore rehearsal before planning destructive work.
- Produce a bounded per-bill duplicate manifest containing IDs, normalized event identity, conflicting metadata, proposed survivor and retained source provenance. Do not extrapolate the initial sample into a deletion count.
- Review timestamp/timezone behavior, repeated-event semantics and metadata conflicts. Preserve useful earliest ingestion/provenance; inventory downstream references and audit requirements.
- Reconcile before/after row counts and distinct-event counts on an isolated restored database. Prove no unique event or referenced identity is lost. Retain rollback material.
- Obtain review of the concrete production manifest, deletion batch size and maintenance window. Do not deploy a blanket full-table deduplication query.
- Measure physical storage after cleanup/maintenance. Deleting tuples does not necessarily return disk space, and provisioned capacity/cost does not automatically shrink. Do not book savings until measured and configuration changes are separately approved.

Tests reproduce the old mismatch, verify legacy reuse without deletion, equivalent timezones, deterministic independent preparation and preservation of distinct bills/dates/text.
