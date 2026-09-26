# Monoline

![Monoline — one sentence, one beat, one slide](web/public/og.png)

**Paste a script. Get a film.**

Monoline is a local, single-user tool that turns a text script into a finished, narrated
explainer video. It is monochrome, deterministic, and runs entirely on your machine — no
account, no upload, no network dependency for the core path.

Monoline is not a video editor and not a generative-video model. It is a pipeline: your text
is segmented into beats, every beat is classified and laid out by content, each beat gets its
own measured voice line, and the result is rendered from HTML to MP4. The same input always
produces the same film.

[中文文档](README_zh.md)

## How a job runs

```
text in  →  outline (review and edit)  →  nine stages  →  MP4  →  Studio (keep editing)
```

1. **Paste text, or generate it.** Markdown pasted from a document, a README or an LLM response
   is parsed by block rather than by source line, so headings, list markers, tables and footnote
   references reach neither the screen nor the voiceover.
2. **Review the outline before anything is paid for.** The segmentation into beats and the
   storyboard for each beat are presented together. Merge, split, delete, reorder, re-type a
   beat, or attach pictures to it. This runs before TTS, so restructuring costs seconds.
3. **Nine cached stages.** `script → tts → assemble → plan → fonts → compose → gate → render →
   deliver`. A process that dies mid-job resumes where it stopped. A re-run never overwrites a
   storyboard you shaped by hand: `?force=1` repaints, it does not re-author.
4. **Keep editing in Studio.** Per-beat re-voicing, slide text, scene kind, layout treatment,
   drag-reorder with audio following, keyboard navigation, live preview.

Timing is derived, never guessed: every line is synthesised separately and its measured
duration tiles the timeline. There is no ASR step, because Whisper mis-decodes Chinese TTS —
the deterministic route is also the accurate one.

## Requirements

| | |
|---|---|
| **uv** | Python 3.11 is pinned; `kokoro-onnx` publishes no 3.14 wheel |
| **Node 22** | per `.nvmrc`; resolved by absolute path, other majors are reported `wrong_version` |
| **ffmpeg + ffprobe** | on `PATH` (`brew install ffmpeg`) |
| **disk** | roughly 2 GB: Chrome Headless Shell, the Kokoro model, render frame cache |

The optional LLM path (script writing, per-beat storyboard suggestions) talks to an
OpenAI-compatible endpoint or a local Ollama, and falls back to rules when it is not configured.

## Quick start

```bash
make bootstrap   # uv sync (py3.11) + pnpm install + producer resolve + hyperframes doctor
make start       # build if missing → spawn the render sidecar → open http://127.0.0.1:8787
```

`make doctor` prints resolved environment truth. `make help` lists every target.

For development with hot reload: `make serve` in one terminal,
`pnpm --filter @monoline/web dev` in another, then open `http://127.0.0.1:5173`.

After editing the SPA, run `pnpm --filter @monoline/web build`. The bundle is served by the
backend from `backend/src/monoline/static/`; `make test` type-checks the SPA but does not build it.

**One data directory, one server.** `monoline start` resumes every job the database says is
running, which is correct after a crash and destructive while another live server owns those
jobs. Startup therefore refuses when a recorded instance is both alive and answering on its
port. Run a second instance against a separate `MONOLINE_APP_DIR` if you need one.

## Architecture

A single Python process is the product. It owns the job store (SQLite), the pipeline, the
per-job workspace, and serves the web UI from the same origin. A thin Node render sidecar
(HyperFrames' producer server) is spawned by Python and dies with it.

```
backend/   Python (uv): FastAPI + pipeline + SQLite + sidecar supervisor   → uv run monoline …
web/       Vite + React + TypeScript (pnpm): monochrome SPA, live preview
sidecar/   Node: @hyperframes/producer startServer — a stateless render leaf
design/    tokens shared by the UI and the video composer (4 themes + ui.json)
docs/      CONFIG.md (live surface) · VISUAL.md (ledger) · PLAN.md · ROADMAP.md (frozen)
```

Rendering is HTML→MP4 via [HyperFrames](https://github.com/heygen-com/hyperframes) (Apache 2.0).
Animation is [GSAP](https://gsap.com), vendored for offline deterministic rendering.

### The invariant

**One beat ↔ one narration segment ↔ one scene.** Every stage depends on it, so it is asserted
end-to-end rather than assumed. It is also why "just merge those two slides" is a design
question rather than a checkbox.

## Tooling

| Target | Purpose |
|---|---|
| `make test` | the gate: backend pytest plus `tsc --noEmit`. Run this, not an ad-hoc pytest. |
| `make warmup` | renders a built-in fixture end-to-end — the cold-start acceptance test |
| `make doctor` | resolved environment truth (node / ffmpeg / chrome / fonts / sidecar) |
| `make bootstrap` | installs everything and verifies the render toolchain |
| `make start` | build → spawn sidecar → open the app |

## Documentation

[`docs/README.md`](docs/README.md) states which file is authoritative and which is frozen.

- **`docs/CONFIG.md`** — every surface the tool exposes: make targets, environment variables, CLI
  commands, all HTTP endpoints, and what is deliberately left unwired. A test compares it against
  the running application in both directions, so it cannot quietly go stale.
- **`docs/VISUAL.md`** — the visual element inventory and the version ledger. Each row carries the
  measurement that justified the change.
- **`docs/PLAN.md`** — the current plan, plus a not-doing list of approaches already falsified.
- **`docs/ROADMAP.md`** — the V1–V30 narrative. Its numbers are frozen snapshots.

## Status

Local, single-user, no authentication. Figures measured on 2026-09-26 with `make test` at
**140 passed**:

**28** scene kinds · **158** inline SVG icons · **25** voices (8 Chinese) · **4** monochrome
themes × **3** layout presets · **3** aspect ratios · MP4 / WebM / MOV export · SRT / VTT
subtitles · poster extraction · bilingual interface (zh / en) · **32** HTTP paths.

- **Editing** — outline review before TTS, three-pane Studio, per-beat re-voicing, drag-reorder,
  a browsable mode library (`#/modes`), per-beat "ask the model for another shape".
- **Visual** — whole-piece layout rotation so consecutive beats never repeat a shape;
  deterministic data visualisation (rings, bars, donuts, sparklines, KPI, quadrant matrix);
  diagrams (flow, radial, steps, arch, cycle, funnel); image assets with a tone-matched shot
  treatment; graded blur-crossfade and directional transitions; narration-paced reveals; LaTeX
  through a vendored KaTeX.
- **Audio** — local Kokoro TTS, background music with sidechain ducking, punctuation never voiced.
- **Typography** — a single owner for on-screen punctuation (GB/T 15834 and clreq), per-kind rules,
  CJK–Latin spacing, and edge-only de-bugging so mid-sentence marks survive on screen.

## Licence

MIT — see [LICENSE](LICENSE).

The MIT grant covers Monoline's own source. Vendored and runtime-downloaded components keep
their own terms, listed in the same file: GSAP (GreenSock Standard License), KaTeX (MIT),
Lucide (ISC), Noto Sans SC (SIL OFL 1.1), HyperFrames (Apache 2.0), Kokoro-82M weights
(Apache 2.0).
