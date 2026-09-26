# Monoline

**paste a script. get a film.** — a local, single-user tool that turns a pasted
text script into a finished narrated explainer video. Monochrome, ultra-minimal.

One Python process is the product: it owns the job store (SQLite), the pipeline,
the per-job workspace, and serves the web UI. A thin Node **render sidecar**
(HyperFrames' producer server) is spawned by Python and dies with it. Rendering
is HTML→MP4 via [HyperFrames](https://github.com/heygen-com/hyperframes) (Apache 2.0).

## Pipeline (one job)
`script → tts → assemble → plan → fonts → compose → gate → render → deliver`
(nine stages, `backend/src/monoline/pipeline/runner.py`; the SPA draws one workflow row per
stage, and a test fails if the two lists ever drift.)

Alignment is deterministic: each line is synthesized separately and its measured
duration tiles the timeline — no ASR (Whisper mis-decodes Chinese TTS).

## Prerequisites
- **uv** (Python 3.11 — pinned; kokoro-onnx has no 3.14 wheel)
- **Node 22** (`.nvmrc`; resolved by absolute path — `make doctor` labels any other major `wrong_version`)
- **ffmpeg + ffprobe** on PATH (`brew install ffmpeg`)
- ~2 GB free disk (Chrome headless shell + Kokoro model + render frame cache)

## Quick start
```bash
make bootstrap   # uv sync (py3.11) + pnpm install + producer resolve + hyperframes doctor
make start       # build-if-missing → spawn sidecar → open http://127.0.0.1:8787
```
Dev (hot reload): terminal 1 `make serve`, terminal 2 `pnpm --filter @monoline/web dev`, open :5173.

`make doctor` prints resolved environment truth. `make help` lists all targets.

## Layout
```
backend/   Python (uv): FastAPI + pipeline + SQLite + sidecar supervisor   → uv run monoline …
web/       Vite + React + TS (pnpm): monochrome SPA, <hyperframes-player> preview
sidecar/   Node: @hyperframes/producer startServer (stateless render leaf)
design/    tokens shared by the web UI and the video composer (mono-ink / mono-paper / mono-noir / mono-slate + ui.json)
```

## Tooling
- `make bootstrap` — install everything + verify the render toolchain.
- `make start` — build-if-missing → spawn sidecar → open the app.
- `make test` — **the gate**: backend pytest + `tsc --noEmit` for the SPA. Run this, not an ad-hoc pytest.
- `make warmup` — render a tiny built-in fixture end-to-end (the cold-start acceptance test; green ⇒ a pasted script will become a real MP4).
- `make doctor` — resolved environment truth (node/ffmpeg/chrome/fonts/sidecar).

After editing the SPA, run `cd web && pnpm build` — the bundle is served by the backend from
`backend/src/monoline/static/` and is **not** part of `make test`.

## Where the docs live
- `docs/CONFIG.md` — **the** surface list: make targets, env vars, CLI commands, all 30 HTTP
  endpoints, and what is deliberately unwired. A test compares it against the running app in
  both directions, so it cannot quietly go stale.
- `docs/VISUAL.md` — the element inventory + the version ledger (every row carries a commit
  hash and the measurement that justified it). This is the authoritative history.
- `docs/PLAN.md` — the current V47–V54 plan, with the numbers each decision was measured on.
- `docs/ROADMAP.md` — historical V1–V30 narrative; its counts are frozen snapshots, not today.

## Status
Local, single-user, no auth. Past a script, get a narrated video; every beat stays editable.
Counts as of 2026-09-26 (`make test` 105 passed): **28 scene kinds**, 158 inline SVG icons,
25 voices (8 Chinese), 4 monochrome themes × 3 layout presets, three aspect ratios,
mp4/webm/mov + SRT/VTT + poster export, bilingual UI (zh/en), deterministic render contract.
- **Core** paste-text → deterministic narrated video; resumable pipeline; SSE live progress; crash reconcile; sidecar render + CLI fallback; long-input guard that warns before you click Generate.
- **Editing** Studio three-pane (beats / live preview / inspector): per-beat narration re-TTS, slide-text edits, kind **and** layout-treatment changes, drag-reorder (audio follows), keyboard nav, a browsable mode library (`#/modes`).
- **Visual** whole-piece layout rotation so consecutive beats don't repeat the same shape; deterministic data-viz (rings, bars, donuts, sparklines, KPI, quadrant/matrix); diagrams (flow / radial / steps / arch / cycle / funnel); image assets with a tone-matched shot treatment; graded blur-crossfade and directional transitions; narration-paced reveals.
- **Audio** local Kokoro TTS; background music with narration ducking; punctuation no longer spoken.
- **Chinese typography** one owner for on-screen punctuation (GB/T 15834 + clreq), per-kind rules, CJK↔latin spacing.
- **LLM** optional script generation and storyboard upgrade (OpenAI-compatible / local Ollama), batched so a small local model never receives the whole piece; graceful when unconfigured.
