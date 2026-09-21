import { describe, expect, it } from "vitest";
import { corpusStaleNote } from "./corpus-stale";

describe("corpusStaleNote", () => {
  it("says nothing for a section the corpus answered", () => {
    expect(corpusStaleNote({})).toBeNull();
    expect(corpusStaleNote({ corpus_stale: false })).toBeNull();
  });

  it("gives the exact date when the payload recorded its computation", () => {
    const note = corpusStaleNote({
      corpus_stale: true,
      corpus_text_as_of: "2026-07-02T13:58:48+00:00",
      corpus_text_as_of_exact: true,
    });
    expect(note).toContain("text and diff below come from a refresh on 2026-07-02.");
    expect(note).toContain("did not serve this section at the last refresh");
  });

  it("treats a row stamp as a bound, not a date", () => {
    for (const exact of [false, undefined]) {
      const note = corpusStaleNote({
        corpus_stale: true,
        corpus_text_as_of: "2026-07-02T13:58:48+00:00",
        corpus_text_as_of_exact: exact,
      });
      expect(note).toContain("a refresh that started on or before 2026-07-02.");
      expect(note).not.toContain("a refresh on 2026-07-02");
    }
  });

  it("omits the date rather than print a malformed one", () => {
    for (const asOf of [null, undefined, "", "yesterday"]) {
      const note = corpusStaleNote({
        corpus_stale: true,
        corpus_text_as_of: asOf,
        corpus_text_as_of_exact: true,
      });
      expect(note).toContain("come from an earlier refresh. Axiom");
    }
  });

  it("says why there is no diff when the stored one was dropped", () => {
    const note = corpusStaleNote({
      corpus_stale: true,
      corpus_text_as_of: "2026-07-02T13:58:48+00:00",
      corpus_diff_dropped: true,
    });
    expect(note).toContain("The current-law text below comes from");
    expect(note).not.toContain("and diff");
    expect(note).toContain("so no diff is shown.");
  });
});
