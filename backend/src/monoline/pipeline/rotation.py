"""V49: a whole-piece pass that breaks runs of one layout.

Measured on the real corpus (43 jobs / 311 scenes): the longest run of consecutive
`statement` beats was **12**, and 96 beats (**30.9%**) sat inside a run longer than two.
Per-beat classification cannot see that — each of those beats is individually the right
answer, and together they read as a deck that only knows one slide.

So this pass looks at the piece, not the beat. When a text run hits MAX_RUN it converts
the surplus beat into the most specific alternative its own words support, and never
invents copy: every slot below is a slice of the same beat.
"""
from __future__ import annotations

import re

MAX_RUN = 2                      # a third identical layout in a row already reads as monotone
TEXT_RUN = {"statement"}         # kinds that dominate the runs today
_QUOTED = re.compile(r"[“「](.{4,}?)[”」]")
_KV = re.compile(r"([\w一-鿿]{2,10})[：:]([^\s：]{1,24})")
_CLAUSE = re.compile(r"[，、：；,;]")


def _lead_body(beat: str) -> tuple[str, str] | None:
    """Split a sentence into a display lead and a body column. Only when both halves are
    substantial — otherwise `statement` is the honest layout and we leave it alone."""
    parts = [p.strip() for p in _CLAUSE.split(beat.strip()) if p.strip()]
    if len(parts) < 2:
        return None
    lead, body = parts[0], "，".join(parts[1:])
    if not (2 <= len(lead) <= 14 and 6 <= len(body) <= 90):
        return None
    return lead, body


def _poster(beat: str) -> dict | None:
    """A quoted clause plus whoever said it → a document card, not another big line."""
    m = _QUOTED.search(beat)
    if not m:
        return None
    quoted = m.group(1).strip("，。、")
    if len(quoted) < 6:
        return None
    before = beat[:m.start()].strip("，。、； ")
    by = before if 2 <= len(before) <= 22 else ""
    return {"kind": "poster", "slots": {"body": quoted, "by": by, "verbatim": True}}


def _cards(beat: str) -> dict | None:
    pairs = [{"k": k.strip(), "v": v.strip("，。、")} for k, v in _KV.findall(beat)]
    pairs = [p for p in pairs if p["k"] and p["v"]]
    if len(pairs) < 2:
        return None
    return {"kind": "cards", "slots": {"title": "", "rows": pairs[:4], "verbatim": True}}


def _split(beat: str) -> dict | None:
    lb = _lead_body(beat)
    if not lb:
        return None
    lead, body = lb
    return {"kind": "split", "slots": {"lead": lead, "body": body, "verbatim": True}}


# most specific first: a quote card beats a card grid beats a two-column text slide
_ALTERNATIVES = (_poster, _cards, _split)


def rebalance(scenes: list[dict], beats: list[str]) -> list[dict]:
    """Rewrite surplus beats inside a long text run. Keeps the scene count and the
    1 beat = 1 scene invariant; only changes kind/slots, and only to a shape the
    beat's own words support."""
    out = [dict(s) for s in scenes]
    run = 0
    prev = None
    for i, sc in enumerate(out):
        kind = sc.get("kind")
        if kind in TEXT_RUN:
            run = run + 1 if kind == prev else 1
        else:
            run = 0
        prev = kind
        if kind not in TEXT_RUN or run <= MAX_RUN:
            continue
        beat = beats[i] if i < len(beats) else ""
        # A beat whose quotation never closes was cut mid-sentence by the segmenter
        # (#113). Splitting it again would put the orphan “ on the slide, so leave it
        # with the statement layout, whose distilled headline stays clean.
        if beat.count("“") != beat.count("”") or beat.count("「") != beat.count("」"):
            continue
        for make in _ALTERNATIVES:
            alt = make(beat)
            if alt:
                out[i] = {"i": i, "kind": alt["kind"], "source": "rules:rotation",
                          "slots": alt["slots"]}
                prev, run = alt["kind"], 0
                break
    return out
