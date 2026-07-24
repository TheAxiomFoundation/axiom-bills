import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// No backend proxy — the frontend talks to Supabase directly via
// @supabase/supabase-js. See packages/web/src/lib/supabase.ts. Set
// VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY in your env / Vercel project.
// Served under https://axiom.org/bills via the main site's reverse proxy.
export default defineConfig({
  base: "/bills/",
  plugins: [react()],
});
