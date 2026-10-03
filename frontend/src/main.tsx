import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("Missing #root element; index.html must provide it.");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>
);