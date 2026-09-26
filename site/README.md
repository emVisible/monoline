# site/

The public landing page for [Monoline](https://github.com/emVisible/monoline). A static
Vite + React + TypeScript bundle, deployed to Vercel. It has no backend, no API calls and no
build-time data fetch — everything it shows is either copy in `src/strings.ts` or an artefact
produced by the product and committed here.

```bash
pnpm install          # from the repo root; this is a workspace package
pnpm --filter @monoline/site dev
pnpm --filter @monoline/site build      # → site/dist
pnpm --filter @monoline/site preview
```

## Deploying to Vercel

1. Push this repository to GitHub.
2. On Vercel, **New Project → import the repository**.
3. Set **Root Directory to `site`** — the default (repo root) builds nothing, because the repo
   root is a pnpm workspace, not the site.
4. Framework preset *Vite*, build command `pnpm build`, output `dist` — `vercel.json` pins the
   last two so a console change cannot silently break the deploy.

No environment variables, no secrets, no server-side functions.

## What the page is made of

| Path | Role |
|---|---|
| `src/App.tsx` | the seven scenes, in reading order |
| `src/components/Scene.tsx` | one scene = one beat: dot-grid wash, corner brackets, eyebrow, folio |
| `src/components/HeroCut.tsx` | the hero: a paragraph cutting itself into beats |
| `src/components/Playhead.tsx` | scroll position rendered as the product's own progress rail |
| `src/hero.json` | **generated fixture** — see below |
| `public/frames/` | real screenshots, not mockups |
| `scripts/capture-outline.mjs` | regenerates `frames/outline.png` from the running app |

## Design tokens are imported, not copied

`src/tokens.ts` reads `../design/tokens/ui.json` — the same file the application's stylesheet
is derived from — and emits it as CSS custom properties. Colours, spacing, radii, durations
and easings therefore cannot drift into a second palette. `tokens.ts` throws at build time if a
token it depends on disappears, so a rename in the product surfaces as a failed build rather
than as a page that quietly renders `undefined`.

## Re-deriving everything the page asserts

The page states numbers. They are measured, not remembered:

```bash
# the eight beats shown in the hero (real segmenter + real rule planner, no mock).
# `--project`, not `--directory`: the latter changes the working directory, and this command
# reads a path relative to the repo root. Verified to reproduce src/hero.json byte for byte.
uv run --project backend python -c "
import json
from monoline.pipeline.segment import segment_text
from monoline.pipeline.planner import RulePlanner
from monoline.pipeline.display_text import detonate
src = open('site/scripts/hero-source.txt').read().strip()
beats = segment_text(src)
scenes = RulePlanner().plan(beats, brand='Monoline', script=src)
print(json.dumps({'source': src,
  'beats': [{'text': detonate(b), 'kind': s['kind']} for b, s in zip(beats, scenes)]},
  ensure_ascii=False, indent=2))" > site/src/hero.json

# the 28 scene kinds
uv run --directory backend python -c "from monoline.ir.sceneplan import KINDS; print(len(KINDS))"

# 25 voices / 8 Chinese, 4 themes, 32 HTTP paths
curl -s localhost:8787/api/voices | python3 -c "import json,sys; print(len(json.load(sys.stdin)['voices']))"
curl -s localhost:8787/api/themes | python3 -c "import json,sys; print(len(json.load(sys.stdin)['themes']))"
curl -s localhost:8787/openapi.json | python3 -c "import json,sys; print(len(json.load(sys.stdin)['paths']))"

# the test count quoted in the determinism scene
make test
```

If a number moves in the product, update `src/strings.ts` in the same change.

## Verification before a commit lands here

`pnpm build`, then a headless pass over the built bundle: three widths (1440 / 768 / 390),
both languages, and `prefers-reduced-motion`. The pass asserts horizontal overflow of 0px, no
element extending past the viewport, no broken image, all eight hero beats revealed, and zero
console/page/request failures. Judging layout from a thumbnail is not verification; the
rectangles are measured.

## Deliberately absent

No analytics, no cookie banner, no newsletter form, no pricing table, no blog, no embedded
video file, no light theme. The page advertises a local tool; it does not phone home.
