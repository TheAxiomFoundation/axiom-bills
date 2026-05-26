import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// No backend proxy — the frontend talks to Supabase directly via
// @supabase/supabase-js. See packages/web/src/lib/supabase.ts. Set
// VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY in your env / Vercel project.
export default defineConfig({
  plugins: [react()],
});
