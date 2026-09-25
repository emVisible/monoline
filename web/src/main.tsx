import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@hyperframes/player"; // registers <hyperframes-player>
import { App } from "./App";
import { LangRoot, applyHtmlLang, lang } from "./i18n";
import "./styles.css";

applyHtmlLang(lang());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LangRoot>{() => <App />}</LangRoot>
  </StrictMode>
);
