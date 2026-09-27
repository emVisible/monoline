// Regenerates site/public/frames/outline-{zh,en}.png — real screenshots of the real outline
// panel, driven through the same flow a user takes (paste → Generate → outline). Nothing is
// staged, and the text typed is read from the same two files `gen-hero.py` cuts the hero demo
// from, so the page's animated hero and its product frame describe the same film — in the
// language the visitor is reading the page in.
//
//   1. start the app:      make start            (or uv run --directory backend monoline start)
//   2. run this:           node site/scripts/capture-outline.mjs [port]
//
// Speaks Chrome DevTools Protocol over the browser's own debugging socket, using only Node
// built-ins (fetch + WebSocket). The previous version needed puppeteer-core, which the repo
// does not depend on — so this command could never have been run from a fresh clone.
// The browser binary is the Playwright headless shell `make warmup` already uses.
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { spawn } from "node:child_process";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const port = process.argv[2] || process.env.MONOLINE_PORT || "8787";
const framesDir = resolve(repo, "site", "public", "frames");
const cdpPort = 9333;
const base = `http://127.0.0.1:${port}`;
const chrome = process.env.CHROME
  || `${process.env.HOME}/Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell`;

const LANGS = [
  { id: "zh", source: "hero-source.txt" },
  { id: "en", source: "hero-source-en.txt" },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- CDP ---------------------------------------------------------------------
let ws, seq = 0;
const pending = new Map();
const events = [];

function send(method, params = {}) {
  const id = ++seq;
  return new Promise((ok, bad) => {
    pending.set(id, { ok, bad });
    ws.send(JSON.stringify({ id, method, params }));
  });
}

function waitEvent(name, timeoutMs = 30000) {
  const hit = events.findIndex((e) => e.method === name);
  if (hit >= 0) return Promise.resolve(events.splice(hit, 1)[0]);
  return new Promise((ok, bad) => {
    const timer = setTimeout(() => bad(new Error(`timeout waiting for ${name}`)), timeoutMs);
    const poll = setInterval(() => {
      const i = events.findIndex((e) => e.method === name);
      if (i >= 0) { clearInterval(poll); clearTimeout(timer); ok(events.splice(i, 1)[0]); }
    }, 25);
  });
}

async function evaluate(expression, { awaitPromise = false } = {}) {
  const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
  return r.result?.value;
}

const browser = spawn(chrome, [
  "--headless", "--no-sandbox", "--disable-gpu",
  `--remote-debugging-port=${cdpPort}`,
  `--user-data-dir=${mkdtempSync(resolve(tmpdir(), "monoline-capture-"))}`,
  "--window-size=1600,900", "about:blank",
], { stdio: "ignore" });

try {
  let list;
  for (let i = 0; i < 60; i++) {
    try { list = await (await fetch(`http://127.0.0.1:${cdpPort}/json/list`)).json(); break; }
    catch { await sleep(250); }
  }
  if (!list) throw new Error("chrome-headless-shell never answered on the debugging port");
  const target = list.find((t) => t.type === "page");
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = () => bad(new Error("CDP socket failed")); });
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) {
      const { ok, bad } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? bad(new Error(msg.error.message)) : ok(msg.result);
    } else if (msg.method) {
      events.push(msg);
    }
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 900, deviceScaleFactor: 1, mobile: false });

  for (const { id, source } of LANGS) {
    const script = readFileSync(resolve(repo, "site", "scripts", source), "utf8").trim();
    const thrown = [];
    const record = () => {
      for (let i = events.length - 1; i >= 0; i--) {
        if (events[i].method === "Runtime.exceptionThrown") {
          thrown.push(events[i].params.exceptionDetails?.exception?.description || "exception");
          events.splice(i, 1);
        }
      }
    };

    await send("Page.navigate", { url: `${base}/` });
    await waitEvent("Page.loadEventFired");
    await evaluate(`localStorage.setItem("monoline.lang", ${JSON.stringify(id)})`);
    await send("Page.navigate", { url: `${base}/#/new` });
    // the app's i18n reads storage at import time, so the switch needs a real reload
    await send("Page.reload", {});
    await waitEvent("Page.loadEventFired");
    await sleep(1200);

    await evaluate(`(() => {
      const ta = document.querySelector("textarea");
      const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      set.call(ta, ${JSON.stringify(script)});
      ta.dispatchEvent(new Event("input", { bubbles: true }));
      return !!ta;
    })()`);
    await sleep(500);
    await evaluate(`document.querySelector("button.generate").click()`);

    let rows = 0;
    for (let i = 0; i < 240 && rows < 1; i++) {
      await sleep(500);
      rows = await evaluate(`document.querySelectorAll(".ol-row").length`);
    }
    await sleep(1400);
    await evaluate("window.scrollTo(0, 0)");
    await sleep(400);
    record();
    rows = await evaluate(`document.querySelectorAll(".ol-row").length`);
    const shot = await send("Page.captureScreenshot", { format: "png" });
    const out = resolve(framesDir, `outline-${id}.png`);
    writeFileSync(out, Buffer.from(shot.data, "base64"));
    if (rows < 2 || thrown.length) {
      console.error(`${id}: capture failed — rows=${rows} exceptions=${thrown.length} ${thrown.slice(0, 2).join(" | ")}`);
      process.exit(1);
    }
    console.log(`wrote ${out} — ${rows} outline rows, 0 uncaught exceptions`);
  }
} finally {
  browser.kill();
}
