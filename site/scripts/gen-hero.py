"""Generate site/src/hero.json — the hero demo's data, from the real pipeline.

Nothing here is written for the page. The beats come out of `monoline.pipeline.segment`
(the same segmenter a job runs) and `monoline.pipeline.planner.RulePlanner` (the same rule
planner), and each beat records WHERE in the source it was cut, so the paragraph can be
marked at its true cut points instead of an equal-count guess.

    uv run --project backend python site/scripts/gen-hero.py > site/src/hero.json

Both languages are generated because the page is bilingual: an English hero showing Chinese
would advertise the tool in one language and demo it in another.
"""
from __future__ import annotations

import json
from pathlib import Path

from monoline.pipeline.display_text import detonate
from monoline.pipeline.planner import RulePlanner
from monoline.pipeline.segment import segment_text

ROOT = Path(__file__).resolve().parents[2]
LANGS = {"zh": "hero-source.txt", "en": "hero-source-en.txt"}


def build(src: str) -> dict:
    beats = segment_text(src)
    scenes = RulePlanner().plan(beats, brand="Monoline", script=src)
    spans: list[list[int]] = []
    pos = 0
    for raw in beats:
        start = src.find(raw, pos)
        if start < 0:
            raise SystemExit(
                f"beat is not a contiguous slice of the source (markdown was stripped or two "
                f"clauses were merged): {raw!r}\nthe demo text must stay plain prose")
        spans.append([start, start + len(raw)])
        pos = start + len(raw)
    return {
        "source": src,
        "spans": spans,
        "beats": [{"text": detonate(b), "kind": s["kind"]} for b, s in zip(beats, scenes)],
    }


def main() -> int:
    out = {}
    for lang, name in LANGS.items():
        path = ROOT / "site" / "scripts" / name
        out[lang] = build(path.read_text().strip())
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
