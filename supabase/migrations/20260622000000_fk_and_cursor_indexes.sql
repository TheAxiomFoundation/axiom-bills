-- Proactive index sweep: close the unindexed-filter gaps that were turning
-- into statement-timeout (57014) failures one at a time as the tables grew.
--
-- Pattern: PostgREST embeds (?select=...,bill_texts(...)) and the scraper's
-- remote-id lookups filter child tables by bill_id, and the federal cursor
-- sorts by last_scraped_at. Where the column wasn't indexed, Postgres did a
-- sequential scan that grew into a timeout. bill_citations already had its
-- bill_id index; versions/texts were missed, and these others were never
-- added.

-- Child-table foreign keys used by detail-page embeds AND scraper child
-- lookups. bill_texts especially holds full bill text, so an unindexed
-- bill_id scan is the most expensive — and the most likely next failure.
create index if not exists idx_bill_versions_bill on bills.bill_versions(bill_id);
create index if not exists idx_bill_texts_bill    on bills.bill_texts(bill_id);

-- bills.session_id is an FK with no index. The sync now routes through the
-- indexed jurisdiction column, but other joins/cascades still benefit.
create index if not exists idx_bills_session on bills.bills(session_id);

-- Federal cursor reads the latest scrape time per jurisdiction
-- (jurisdiction=eq.us & order=last_scraped_at.desc & limit 1). Index the
-- sort so it's a top-1 probe instead of sorting every federal row each hour.
create index if not exists idx_bills_juris_scraped
  on bills.bills(jurisdiction, last_scraped_at desc);
