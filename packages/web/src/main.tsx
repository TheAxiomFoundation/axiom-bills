import React from "react";
import ReactDOM from "react-dom/client";
import posthog from "posthog-js";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Home } from "./pages/Home";
import { JurisdictionPage } from "./pages/JurisdictionPage";
import { BillPage } from "./pages/BillPage";
import { CoveragePage } from "./pages/CoveragePage";
import "./styles.css";

// Product analytics → PostHog. GA4 (G-2YHG89FY0N) is wired separately in
// index.html / public/analytics.js; PostHog runs alongside it.
// Browser-only, and guarded so StrictMode double-invocation can't re-init.
declare global {
  interface Window {
    __posthogInitialized?: boolean;
  }
}

if (typeof window !== "undefined" && !window.__posthogInitialized) {
  window.__posthogInitialized = true;
  posthog.init("phc_mrEaBroaYTRUrdkfhJYBGMpafKXWEdUyw5VPQnheh37m", {
    api_host: "https://us.i.posthog.com",
    defaults: "2026-01-30",
    person_profiles: "identified_only",
    respect_dnt: true,
    capture_pageview: "history_change",
  });
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, "")}>
        <Routes>
          <Route element={<App />}>
            <Route path="/" element={<Home />} />
            <Route path="/coverage" element={<CoveragePage />} />
            <Route path="/j/:code" element={<JurisdictionPage />} />
            <Route path="/bills/:billId" element={<BillPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>,
);
