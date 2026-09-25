"""Wrap user-facing Chinese literals in t() across the SPA.

Position matters and a blind replace gets it wrong, so this walks the file with a small
scanner that knows comments from code, then rewrites only inside code:
  1. JSX attribute   label="中文"   ->  label={t("中文")}
  2. JSX text        >中文<         ->  >{t("中文")}<
  3. plain string    ("中文")       ->  (t("中文"))
Backtick templates are reported, not rewritten: they hold ${} interpolation and need a
placeholder key. Modes-registry `zh:` / `desc:` fields are data, not chrome — skipped.
"""
import json
import re
import sys
from pathlib import Path

CJK = re.compile(r"[一-鿿]")
SRC = Path(__file__).resolve().parents[2] / "web" / "src"
FILES = ["App.tsx", "Studio.tsx", "modes.tsx"]
SKIP_KEYS = re.compile(r"\b(zh|descEn|en)\s*:\s*$")     # data fields handled by hand

ATTR = re.compile(r'([\w-]+)="([^"]*)"')
TEXT = re.compile(r">([^<>]*)<")
STR = re.compile(r'"((?:[^"\\\n]|\\.)*)"')


def split_code(src: str):
    """Yield (is_code, span) covering the whole file. Only comments are excluded — strings
    are the target, but they are still consumed here so a `//` inside one is not read as a
    comment start."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            out.append((False, src[i:n if j < 0 else j]))
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            out.append((False, src[i:n if j < 0 else j + 2]))
            i = n if j < 0 else j + 2
            continue
        if c in '"\'`':
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append((True, src[i:min(j + 1, n)]))
            i = min(j + 1, n)
            continue
        out.append((True, src[i:i + 1]))
        i += 1
    merged = []
    for code, span in out:
        if merged and merged[-1][0] == code:
            merged[-1][1] += span
        else:
            merged.append([code, span])
    return merged


def already_wrapped(text: str, at: int) -> bool:
    return text[:at].rstrip().endswith("t(")


def rewrite_code(chunk: str, tally: dict):
    def attr(m):
        name, val = m.group(1), m.group(2)
        if not CJK.search(val) or SKIP_KEYS.search(m.string[:m.start()]):
            return m.group(0)
        tally.setdefault("attr", []).append(val)
        return f'{name}={{t("{val}")}}'

    def text(m):
        inner = m.group(1)
        if not CJK.search(inner) or "{" in inner or "}" in inner or already_wrapped(m.string, m.start()):
            return m.group(0)
        lead = inner[:len(inner) - len(inner.lstrip())]
        trail = inner[len(inner.rstrip()):]
        body = inner.strip()
        if not body:
            return m.group(0)
        tally.setdefault("jsx", []).append(body)
        return f">{lead}{{t(\"{body}\")}}{trail}<"

    def string(m):
        val = m.group(1)
        at = m.start()
        if not CJK.search(val) or already_wrapped(m.string, at):
            return m.group(0)
        # a bare object value `key: "中文"` is data unless the caller knows better; keep it
        if SKIP_KEYS.search(m.string[:at]):
            return m.group(0)
        tally.setdefault("str", []).append(val)
        return f't("{val}")'

    chunk = ATTR.sub(attr, chunk)
    chunk = TEXT.sub(text, chunk)
    return STR.sub(string, chunk)


def main():
    dry = "--dry" in sys.argv
    tally, out_files = {}, {}
    for name in FILES:
        src = (SRC / name).read_text()
        pieces = []
        for is_code, span in split_code(src):
            if is_code:
                span = rewrite_code(span, tally)
            pieces.append(span)
        out_files[name] = "".join(pieces)
        for line in re.finditer(r"`[^`\n]*[一-鿿][^`\n]*`", src):
            tally.setdefault("skip_template", []).append(line.group(0))

    inv = {k: sorted(dict.fromkeys(v)) for k, v in tally.items()}
    Path("/tmp/i18n_inventory.json").write_text(json.dumps(inv, ensure_ascii=False, indent=1))
    print({k: len(v) for k, v in inv.items()})
    if not dry:
        for name, body in out_files.items():
            (SRC / name).write_text(body)
        print("written:", ", ".join(out_files))


main()
