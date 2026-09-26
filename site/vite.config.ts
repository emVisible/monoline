import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The site reads the product's own design tokens (../design/tokens/ui.json) rather than
// copying them, so the marketing page cannot drift away from the app it advertises.
// fs.allow is what lets the dev server resolve a file outside the project root.
export default defineConfig({
  plugins: [react()],
  server: { fs: { allow: [".."] } },
  build: { outDir: "dist", emptyOutDir: true },
});
