import type { BillDiffSection } from "./api";

/**
 * The line shown above a section whose current-law text was kept from an
 * earlier refresh because the live corpus no longer answers for it.
 * Null for every other section. The date is the latest the text can date
 * from: the refresh stamps it when it scrapes the bill, and the payload
 * carries no computation time of its own.
 */
export function corpusStaleNote(
  section: Pick<BillDiffSection, "corpus_stale" | "corpus_text_as_of">,
): string | null {
  if (!section.corpus_stale) return null;
  const asOf = section.corpus_text_as_of?.slice(0, 10);
  const when =
    asOf && /^\d{4}-\d{2}-\d{2}$/.test(asOf) ? ` on or before ${asOf}` : "";
  return (
    `The current-law text and diff below were computed${when}. ` +
    "Axiom's corpus did not serve this section at the last refresh, so " +
    "they have not been checked against the law since. The bill text and " +
    "the official source remain the source of truth."
  );
}
