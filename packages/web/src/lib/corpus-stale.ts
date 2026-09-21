import type { BillDiffSection } from "./api";

type StaleFields = Pick<
  BillDiffSection,
  | "corpus_stale"
  | "corpus_text_as_of"
  | "corpus_text_as_of_exact"
  | "corpus_diff_dropped"
>;

/**
 * The line shown above a section whose current-law text was kept from an
 * earlier refresh because the live corpus no longer answers for it.
 * Null for every other section.
 *
 * Newer payloads record when they were computed, and that date is exact.
 * Older ones only carry the time the refresh stamped on the bill's row,
 * which says the text comes from a refresh that started on or before it.
 */
export function corpusStaleNote(section: StaleFields): string | null {
  if (!section.corpus_stale) return null;
  const asOf = section.corpus_text_as_of?.slice(0, 10);
  const dated = Boolean(asOf && /^\d{4}-\d{2}-\d{2}$/.test(asOf));
  const when = !dated
    ? " an earlier refresh"
    : section.corpus_text_as_of_exact
      ? ` a refresh on ${asOf}`
      : ` a refresh that started on or before ${asOf}`;
  const what = section.corpus_diff_dropped
    ? "The current-law text below comes from"
    : "The current-law text and diff below come from";
  const dropped = section.corpus_diff_dropped
    ? " The bill's instructions read differently now than they did then," +
      " so no diff is shown."
    : "";
  return (
    `${what}${when}. ` +
    "Axiom's corpus did not serve this section at the last refresh, so " +
    "the text has not been checked against the law since." +
    dropped +
    " The bill text and the official source remain the source of truth."
  );
}
