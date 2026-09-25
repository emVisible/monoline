"""V50: the UI is bilingual, so no Chinese literal may reach the screen without a key.

The rule this enforces: every CJK string literal in the SPA sources must be reachable by
`t()` — either it is wrapped at the use site, or it is a value in a data map whose lookups
are all wrapped. Concretely, the test extracts (a) every literal passed to t() and every
literal stored in a `*_LABEL`/registry value, and requires an English entry for it, and
(b) rejects any CJK literal that sits in code but is neither wrapped nor stored in one of
those maps — that is the shape a future edit takes when someone types a new label by hand.

Scanning is character-wise because a regex over the raw file mistakes the `//` inside
"https://…" for a comment start and silently drops the rest of the line.
"""
from __future__ import annotations

import re
from pathlib import Path

CJK = re.compile(r"[一-鿿]")
STR = re.compile(r'"((?:[^"\\\n]|\\.)*)"')
WEB = Path(__file__).resolve().parents[2] / "web" / "src"
SOURCES = ["App.tsx", "Studio.tsx", "modes.tsx"]
# data maps / registry fields: Chinese is stored here and translated where it is read
DATA_FIELD = re.compile(r"\b(zh|desc|note|label|title|name|script|tts|assemble|plan|fonts|"
                        r"compose|gate|render|deliver|node|ffmpeg|gsap_vendored|ofl_cjk_font|"
                        r"chrome|hyperframes|render_sidecar|list|flow|radial|steps|funnel|"
                        r"matrix|cards|table|rows|share|trend|kpi|stat|bars|cycle|arch|image)\s*:\s*$")


def strip_comments(src: str) -> str:
    """Blank out // and /* */ comments while leaving strings intact."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'":                                   # skip over a string literal
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:min(j + 1, n)])
            i = min(j + 1, n)
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(" " * (j - i))
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def literals(src: str):
    """Yield (value, wrapped_at_use, in_data_field) for every CJK string literal."""
    clean = strip_comments(src)
    for m in STR.finditer(clean):
        val = m.group(1)
        if not CJK.search(val):
            continue
        before = clean[:m.start()].rstrip()
        wrapped = before.endswith("t(")
        data = bool(DATA_FIELD.search(before))
        yield val, wrapped, data


def dictionary() -> set[str]:
    """Keys as they exist at runtime: `\n` in the source is a real newline in the value."""
    src = (WEB / "strings.ts").read_text()
    return {m.group(1).replace("\\n", "\n")
            for m in re.finditer(r'(?m)^[ \t]+"((?:[^"\\]|\\.)*)"[ \t]*:', src)}


def test_every_ui_literal_has_an_english_entry():
    en = dictionary()
    assert len(en) > 150, f"suspiciously small dictionary: {len(en)}"
    missing, loose = [], []
    for name in SOURCES:
        for val, wrapped, data in literals((WEB / name).read_text()):
            key = val.replace("\\n", "\n")
            if key not in en:
                missing.append((name, key))
            if not wrapped and not data:
                loose.append((name, key))
    missing = sorted(set(missing))
    assert not missing, f"{len(missing)} UI literals have no English entry:\n" + \
        "\n".join(f"  {n}: {k[:60]!r}" for n, k in missing[:15])
    loose = sorted(set(loose))
    assert not loose, "CJK literals rendered without t() and not stored in a data map:\n" + \
        "\n".join(f"  {n}: {k[:60]!r}" for n, k in loose[:15])


def test_dictionary_has_no_dead_entries():
    """A key nobody can reach is a translation nobody will ever see — usually a renamed label."""
    used: set[str] = set()
    for name in SOURCES:
        for val, _, _ in literals((WEB / name).read_text()):
            used.add(val.replace("\\n", "\n"))
    dead = sorted(dictionary() - used)
    assert not dead, f"{len(dead)} dictionary entries match no literal in the SPA:\n" + \
        "\n".join(f"  {k[:60]!r}" for k in dead[:15])
