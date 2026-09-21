import { describe, expect, it } from "vitest";
import { corpusStaleNote } from "./corpus-stale";

describe("corpusStaleNote", () => {
  it("says nothing for a section the corpus answered", () => {
    expect(corpusStaleNote({})).toBeNull();
    expect(corpusStaleNote({ corpus_stale: false })).toBeNull();
  });

  it("dates the text when the refresh recorded when it was computed", () => {
    const note = corpusStaleNote({
      corpus_stale: true,
      corpus_text_as_of: "2026-07-02T13:58:48+00:00",
    });
    expect(note).toContain("computed on or before 2026-07-02.");
    expect(note).toContain("did not serve this section at the last refresh");
  });

  it("omits the date rather than print a malformed one", () => {
    for (const asOf of [null, undefined, "", "yesterday"]) {
      const note = corpusStaleNote({
        corpus_stale: true,
        corpus_text_as_of: asOf,
      });
      expect(note).toContain("were computed. Axiom");
    }
  });
});
