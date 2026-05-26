// Helpers shared by the BillVariants summary section and the per-diff
// RuleSpec panel — both render the reencoder's free-form notes and want
// the same parsing + whitespace cleanup.

/** Replace runs of whitespace AND Python repr escapes (\n, \t, \r) with single spaces. */
export function clean(s: string): string {
  return s
    .replace(/\\[nrt]/g, " ")   // literal backslash-n etc. from Python repr()
    .replace(/\s+/g, " ")
    .trim();
}

/** Parse the reencoder's "needle=... payload=..." note into structured halves. */
export function parseScalarNote(
  note: string,
): { kind: string; needle: string; payload: string } | null {
  const m = note.match(
    /^Op (\S+) needle\/payload not a recognized scalar \(needle=(['"])(.*?)\2, payload=(['"])(.*?)\4\)\.?$/s,
  );
  if (!m) return null;
  return { kind: m[1], needle: m[3], payload: m[5] };
}
