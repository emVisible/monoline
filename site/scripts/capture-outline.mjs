// Regenerates site/public/frames/outline.png — a real screenshot of the real outline panel,
// driven through the same flow a user takes (paste → Generate → outline). Nothing is staged:
// the script types the same eight sentences that `hero.json` was cut from, so the page's
// hero demo and its product frame describe the same film.
//
//   1. start the app:      make start            (or uv run --directory backend monoline start)
//   2. run this:           node site/scripts/capture-outline.mjs [port]
//
// Requires the repo's own puppeteer-core + the Playwright headless shell already used by
// `make warmup`. Fails loudly if the panel never renders.
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const require = createRequire(resolve(repo, "package.json"));
const puppeteer = require("puppeteer-core");
const port = process.argv[2] || process.env.MONOLINE_PORT || "8787";
const out = resolve(repo, "site", "public", "frames", "outline.png");

const SCRIPT = "深海里的生物大多能自己发光。这不是反射阳光，而是发生在体内的化学反应。荧光素遇到氧，光子就被放了出来。大约76%的深海动物会发光。三个类群占大多数：灯笼鱼、斧头鱼，以及吸血鬼乌贼。蓝绿色的光在水中传得最远，所以多数信号用它。有些鮟鱇能看见红色，而深处几乎没有别的生物看得见红色。生物发光是地球上最常见的交流方式。";

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME || `${process.env.HOME}/Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell`,
  args: ["--no-sandbox"],
});
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
await page.setViewport({ width: 1600, height: 900, deviceScaleFactor: 1 });

const base = `http://127.0.0.1:${port}`;
await page.goto(`${base}/`, { waitUntil: "networkidle2" });
await page.evaluate(() => localStorage.setItem("monoline.lang", "en"));
await page.goto(`${base}/#/new`, { waitUntil: "networkidle2" });
// the i18n module reads storage at import time, so the switch needs a real reload
await page.reload({ waitUntil: "networkidle2" });
await new Promise((r) => setTimeout(r, 900));

await page.evaluate((text) => {
  const ta = document.querySelector("textarea");
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
  set.call(ta, text);
  ta.dispatchEvent(new Event("input", { bubbles: true }));
}, SCRIPT);
await new Promise((r) => setTimeout(r, 400));

await page.click("button.generate");
await page.waitForSelector(".ol-row", { timeout: 90000 });
await new Promise((r) => setTimeout(r, 1200));
await page.evaluate(() => window.scrollTo(0, 0));
await new Promise((r) => setTimeout(r, 350));

const rows = await page.$$eval(".ol-row", (els) => els.length);
await page.screenshot({ path: out });
await browser.close();

if (rows < 2 || errors.length) {
  console.error(`capture failed: rows=${rows} errors=${errors.length} ${errors.slice(0, 3).join(" | ")}`);
  process.exit(1);
}
console.log(`wrote ${out} — ${rows} outline rows, 0 page errors`);
