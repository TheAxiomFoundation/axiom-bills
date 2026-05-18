import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { App } from "./App";
import { Home } from "./pages/Home";
import { JurisdictionPage } from "./pages/JurisdictionPage";
import { BillPage } from "./pages/BillPage";
import { RecentPage } from "./pages/RecentPage";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route path="/" element={<Home />} />
          <Route path="/recent" element={<RecentPage />} />
          <Route path="/j/:code" element={<JurisdictionPage />} />
          <Route path="/bills/:billId" element={<BillPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
