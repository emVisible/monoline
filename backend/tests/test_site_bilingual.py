"""The marketing page is bilingual, so its fixture has to be bilingual too.

Reported by eye, not by a test: the page's chrome translated while the hero demo it advertises
stayed Chinese — `hero.json` held one script, and `frames/outline.png` one screenshot. A page
that says "8 sentences in, 8 beats out" in English and then shows a Chinese paragraph is
worse than an untranslated page: it claims something the picture contradicts.

These are source-of-truth checks on the generated artifact, which is where the language
actually lives. The animation itself is verified in a browser (site/README.md).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "site"
HERO = SITE / "src" / "hero.json"
STRINGS = SITE / "src" / "strings.ts"
FRAMES = SITE / "public" / "frames"

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def hero() -> dict:
    return json.loads(HERO.read_text())


def test_both_languages_are_present_and_agree_on_shape():
    data = hero()
    assert set(data) == {"en", "zh"}, f"hero.json keys: {sorted(data)}"
    counts = {L: len(v["beats"]) for L, v in data.items()}
    assert counts["en"] == counts["zh"], f"the two demos are not the same film: {counts}"
    for lang, v in data.items():
        assert len(v["spans"]) == len(v["beats"]), f"{lang}: spans and beats disagree"


def test_the_english_demo_is_actually_english():
    """The regression this catches: a fixture generated once for one language and reused."""
    en = hero()["en"]
    assert not CJK.search(en["source"]), "Chinese in the English hero input"
    for b in en["beats"]:
        assert not CJK.search(b["text"]), f"Chinese beat in the English demo: {b['text']!r}"
    assert CJK.search(hero()["zh"]["source"]), "the Chinese demo lost its Chinese"


def test_every_beat_span_points_at_its_own_text():
    """`HeroCut` paints the source at these offsets, so a span that doesn't hold its beat's
    text would mark the wrong words — the animation would lie about where the cut fell."""
    for lang, v in hero().items():
        src = v["source"]
        prev_end = 0
        for span, beat in zip(v["spans"], v["beats"]):
            start, end = span
            assert start >= prev_end, f"{lang}: spans overlap or run backwards at {start}"
            shown = beat["text"]
            assert src[start:end].startswith(shown[:6]), \
                f"{lang}: span {src[start:end]!r} does not contain {shown!r}"
            prev_end = end


def test_every_string_has_both_halves_and_no_english_half_is_chinese():
    src = STRINGS.read_text()
    pairs = re.findall(r'\{\s*en:\s*"((?:[^"\\]|\\.)*)".*?zh:\s*"((?:[^"\\]|\\.)*)"\s*\}', src, re.S)
    assert len(pairs) > 30, f"the scanner found {len(pairs)} pairs — strings.ts changed shape?"
    for en, zh in pairs:
        assert en.strip() and zh.strip(), "empty half"
        assert not CJK.search(en), f"CJK in an en value: {en[:40]!r}"


def test_the_page_has_a_frame_per_language():
    for lang in ("en", "zh"):
        assert (FRAMES / f"outline-{lang}.png").stat().st_size > 20_000, f"outline-{lang}.png missing/tiny"
