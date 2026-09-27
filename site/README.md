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
5. Add the environment variable **`VITE_SITE_URL` = `https://<your-deployment>`**. It feeds
   `<link rel="canonical">` and `og:url`; unset, both fall back to the repository URL, which is
   true but not the page. `og:image` is deliberately pinned to `raw.githubusercontent.com`
   instead, so a shared link renders its card before any of this exists.

No secrets, no server-side functions. `robots.txt` allows the whole page; there is no sitemap
because there is one URL.

## What the page is made of

| Path | Role |
|---|---|
| `src/App.tsx` | the seven scenes, in reading order |
| `src/components/Scene.tsx` | one scene = one beat: dot-grid wash, corner brackets, eyebrow, folio |
| `src/components/HeroCut.tsx` | the hero: a paragraph cutting itself into beats |
| `src/components/Playhead.tsx` | scroll position rendered as the product's own progress rail |
| `src/hero.json` | **generated fixture, one entry per language** — see below |
| `public/frames/` | real screenshots, not mockups; `outline-<lang>.png` per language |
| `scripts/gen-hero.py` | regenerates `src/hero.json` with the real segmenter + rule planner |
| `scripts/hero-source.txt` / `scripts/hero-source-en.txt` | the two demo scripts the hero cuts |
| `scripts/capture-outline.mjs` | regenerates `frames/outline-{zh,en}.png` from the running app |

## Design tokens are imported, not copied

`src/tokens.ts` reads `../design/tokens/ui.json` — the same file the application's stylesheet
is derived from — and emits it as CSS custom properties. Colours, spacing, radii, durations
and easings therefore cannot drift into a second palette. `tokens.ts` throws at build time if a
token it depends on disappears, so a rename in the product surfaces as a failed build rather
than as a page that quietly renders `undefined`.

## Re-deriving everything the page asserts

The page states numbers. They are measured, not remembered:

```bash
# the hero demo, both languages (real segmenter + real rule planner, no mock). `--project`,
# not `--directory`: the latter changes the working directory. Verified to reproduce
# src/hero.json byte for byte.
uv run --project backend python site/scripts/gen-hero.py > site/src/hero.json

# the product frame in both languages — needs the app running (make start)
node site/scripts/capture-outline.mjs 8787

# the 28 scene kinds
uv run --project backend python -c "from monoline.ir.sceneplan import KINDS; print(len(KINDS))"

# 25 voices / 8 Chinese, 4 themes, 32 HTTP paths
curl -s localhost:8787/api/voices | python3 -c "import json,sys; print(len(json.load(sys.stdin)['voices']))"
curl -s localhost:8787/api/themes | python3 -c "import json,sys; print(len(json.load(sys.stdin)['themes']))"
curl -s localhost:8787/openapi.json | python3 -c "import json,sys; print(len(json.load(sys.stdin)['paths']))"

# the test count quoted in the determinism scene
make test
```

If a number moves in the product, update `src/strings.ts` in the same change.

`backend/tests/test_site_bilingual.py` holds the line on the fixture itself: both languages
present, same beat count, every span pointing at its own text, no Chinese in an English
value. It was written after the page shipped with English chrome around a Chinese demo.

## Verification before a commit lands here

`pnpm build`, then a headless pass over the built bundle: three widths (1440 / 900 / 390),
both languages, and `prefers-reduced-motion`. The pass asserts horizontal overflow of 0px, no
element extending past the viewport, no broken image, all eight hero beats revealed, every
scene heading at opacity 1 after a scroll walk, and zero console/page/request failures.

Language purity is asserted, not eyeballed: the pass walks every text node in the rendered DOM
and counts CJK codepoints. In English mode the only two allowed are the 「中文」 label on the
language switch, which names its language in its own script. Measured on the current build:
`en` → 2 CJK characters at all three widths, `zh` → 727. Judging layout from a thumbnail is not
verification; the rectangles and the counts are measured.

## Deliberately absent

No analytics, no cookie banner, no newsletter form, no pricing table, no blog, no embedded
video file, no light theme. The page advertises a local tool; it does not phone home.
