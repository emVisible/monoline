import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { injectTokens } from "./tokens";
import { LangRoot } from "./i18n";
import App from "./App";
import "./styles.css";

injectTokens();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LangRoot>{() => <App />}</LangRoot>
  </StrictMode>,
);
