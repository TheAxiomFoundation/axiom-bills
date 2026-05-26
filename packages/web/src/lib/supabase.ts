import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

if (!url || !anonKey) {
  throw new Error(
    "VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY must be set in env",
  );
}

// The bills schema is exposed via PostgREST's `db.schema` setting on
// the Supabase project. We point the client at it explicitly so all
// `.from()` calls hit `bills.*` without per-call profile headers.
export const supabase = createClient(url, anonKey, {
  db: { schema: "bills" },
  auth: { persistSession: false },
});
