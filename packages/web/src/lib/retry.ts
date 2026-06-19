// Retry transient read failures with exponential backoff.
//
// The data layer reads from Supabase over the network. Cold starts, brief
// connection resets, and 5xx blips are transient — a second attempt a
// fraction of a second later usually succeeds. Without this, a single blip
// surfaces as a hard, dead-end error to the user, which is most of what
// "it breaks all the time" actually was.
//
// We only retry things that look transient. A real error (bad query, RLS
// denial, missing relationship) fails fast on the first attempt so it still
// surfaces clearly instead of being masked by repeated tries.

// PostgREST surfaces the underlying Postgres SQLSTATE in `error.code`.
// These are the connection/availability ones worth retrying.
const TRANSIENT_PG_CODES = new Set([
  "08000", // connection_exception
  "08006", // connection_failure
  "08003", // connection_does_not_exist
  "57P03", // cannot_connect_now (server starting up)
  "53300", // too_many_connections
  "XX000", // internal_error
]);

const TRANSIENT_HTTP_CODES = new Set(["502", "503", "504"]);

export function isTransient(error: unknown): boolean {
  if (error == null) return false;

  // A raw fetch failure (offline, DNS, connection reset) rejects with a
  // TypeError ("Failed to fetch") — no structured fields to inspect.
  if (error instanceof TypeError) return true;

  const e = error as { code?: unknown; message?: unknown };
  const code = typeof e.code === "string" ? e.code : "";
  if (TRANSIENT_PG_CODES.has(code) || TRANSIENT_HTTP_CODES.has(code)) {
    return true;
  }

  const msg = (typeof e.message === "string" ? e.message : "").toLowerCase();
  return (
    msg.includes("failed to fetch") ||
    msg.includes("networkerror") ||
    msg.includes("network error") ||
    msg.includes("timeout") ||
    msg.includes("temporarily unavailable")
  );
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Re-invoke `fn` on transient failure. `fn` should build and run a fresh
// request each call (so passing `() => api.jurisdictions()` is safe — every
// attempt issues new queries).
export async function retry<T>(
  fn: () => Promise<T>,
  { attempts = 3, baseDelayMs = 300 }: { attempts?: number; baseDelayMs?: number } = {},
): Promise<T> {
  let lastError: unknown;
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      if (attempt === attempts - 1 || !isTransient(error)) throw error;
      await sleep(baseDelayMs * 2 ** attempt);
    }
  }
  throw lastError;
}
