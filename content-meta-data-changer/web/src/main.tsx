import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import App from "./App";
import FactoryPage from "./FactoryPage";
import HomePage from "./HomePage";
import OfmListPage from "./OfmListPage";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/editor" element={<App />} />
        <Route path="/editor/:fileId" element={<App />} />
        <Route path="/factory" element={<OfmListPage />} />
        <Route path="/factory/:ofmId" element={<FactoryPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
