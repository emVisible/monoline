import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The site reads the product's own design tokens (../design/tokens/ui.json) rather than
// copying them, so the marketing page cannot drift away from the app it advertises.
// fs.allow is what lets the dev server resolve a file outside the project root.
//
// `%SITE_URL%` in index.html is the canonical origin, and it has to have a value even when
// nobody set one: an unsubstituted token in a deployed page is a broken canonical, and a
// local `pnpm build` must not be able to produce one. Until the site gets its own origin the
// repository is the honest canonical. `loadEnv` rather than `process.env` because this file
// is typechecked by `make test`, and the site has no @types/node — the first version of this
// line failed the gate exactly that way.
const REPO = "https://github.com/emVisible/monoline";

export default defineConfig(({ mode }) => {
  const siteUrl = loadEnv(mode, ".", "VITE_").VITE_SITE_URL || REPO;

  return {
    plugins: [
      react(),
      {
        name: "monoline:site-url",
        transformIndexHtml: (html: string) => html.replaceAll("%SITE_URL%", siteUrl),
      },
    ],
    server: { fs: { allow: [".."] } },
    build: { outDir: "dist", emptyOutDir: true },
  };
});
