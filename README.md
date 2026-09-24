# Monoline

**paste a script. get a film.** — a local, single-user tool that turns a pasted
text script into a finished narrated explainer video. Monochrome, ultra-minimal.

One Python process is the product: it owns the job store (SQLite), the pipeline,
the per-job workspace, and serves the web UI. A thin Node **render sidecar**
(HyperFrames' producer server) is spawned by Python and dies with it. Rendering
is HTML→MP4 via [HyperFrames](https://github.com/heygen-com/hyperframes) (Apache 2.0).

## Pipeline (one job)
`script → per-sentence TTS (Kokoro, local) → timings IR (duration-accumulation) →
scene-plan → HTML composition → OFL CJK font subset → lint/check gate → render → MP4`

Alignment is deterministic: each line is synthesized separately and its measured
duration tiles the timeline — no ASR (Whisper mis-decodes Chinese TTS).

## Prerequisites
- **uv** (Python 3.11 — pinned; kokoro-onnx has no 3.14 wheel)
- **Node 22** (`.nvmrc`; the tool resolves node by absolute path — homebrew node 26 is rejected)
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
- `make warmup` — render a tiny built-in fixture end-to-end (the cold-start acceptance test; green ⇒ a pasted script will become a real MP4).
- `make doctor` — resolved environment truth (node/ffmpeg/chrome/fonts/sidecar).

## Status
Feature-complete through the V5 roadmap (see `docs/ROADMAP.md`):
- **Core** paste-text → deterministic narrated MP4; resumable pipeline; SSE live progress; crash reconcile; sidecar render + CLI fallback.
- **Editing** Studio three-pane (beats / live preview / inspector): per-beat narration re-TTS, slide-text edits, kind changes, **drag-reorder** (audio follows), **keyboard nav**, live preview refresh.
- **Visual** 4 monochrome themes + custom accent/brand + presets; inline SVG icon system; deterministic data-viz (progress rings, proportional bars); image assets (upload → frozen into the composition); portrait / square / landscape with adaptive type; graded blur-crossfade transitions.
- **Audio** local Kokoro TTS; background music with narration ducking.
- **Delivery** mp4 / webm / mov export; **SRT / VTT** subtitle sidecars; **cover** frame extraction; a poster-thumbnail History gallery.
- **LLM** optional script generation (OpenAI-compatible / local Ollama), graceful when unconfigured.
