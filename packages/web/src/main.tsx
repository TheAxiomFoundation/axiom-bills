import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Home } from "./pages/Home";
import { JurisdictionPage } from "./pages/JurisdictionPage";
import { BillPage } from "./pages/BillPage";
import { CoveragePage } from "./pages/CoveragePage";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
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
