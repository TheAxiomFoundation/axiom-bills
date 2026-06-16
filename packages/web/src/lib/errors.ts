// Turn whatever lands in a `.catch()` into a human-readable string.
//
// The data layer talks to Supabase, so most rejections are PostgrestError
// objects ({ message, details, hint, code }) — plain objects, not Error
// instances. `String(err)` on those yields the useless "[object Object]",
// which is what users were seeing on screen. Pull out the real message.

type PostgrestLike = {
  message?: unknown;
  details?: unknown;
  hint?: unknown;
  code?: unknown;
};

export function errorMessage(err: unknown): string {
  if (err == null) return "Unknown error";
  if (typeof err === "string") return err;
  if (err instanceof Error) return err.message;

  if (typeof err === "object") {
    const e = err as PostgrestLike;
    if (typeof e.message === "string" && e.message) {
      const parts = [e.message];
      if (typeof e.hint === "string" && e.hint) parts.push(`(hint: ${e.hint})`);
      if (typeof e.code === "string" && e.code) parts.push(`[${e.code}]`);
      return parts.join(" ");
    }
    try {
      return JSON.stringify(err);
    } catch {
      return String(err);
    }
  }

  return String(err);
}
