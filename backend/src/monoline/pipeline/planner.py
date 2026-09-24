"""Scene planner — classify each beat by CONTENT and extract slots.

M1's failure: every middle beat became `statement` with headline = the whole
sentence → "black bg + one big line". The PoC looked good because scenes were
hand-designed (stat numbers, k-v tables, compare, quote). This recovers that
automatically, deterministically, and explainably (each scene records `source`).

Pluggable: `ScenePlanner` protocol; `RulePlanner` is v1. `LLMPlanner` later emits
the same scene dicts and goes through the same validator.
"""
from __future__ import annotations

import re
from typing import Protocol

from .segment import SentenceSegmenter  # noqa: F401  (re-export for callers)

# Number + unit / arrow tokens that deserve a `stat` treatment.
_NUM = re.compile(r"([↓↑]?\s*[\d][\d.,]*\s*(?:%|％|倍|万|亿|千|美元|美金|元|块|ms|s|秒|分钟|小时|天|周|月|年|K|M|G|GB|Token|token)?)")
_KV = re.compile(r"([\u4e00-\u9fa5A-Za-z][\w\u4e00-\u9fa5 ]{0,8})\s*[：:]\s*([^，,。；;！!？?]+)")
_QUOTE_WRAP = re.compile(r"^[「“\"『《](.+?)[」”\"』》]$")
_DEF = re.compile(r"^(.{2,10}?)\s*(?:是|是指|称为|叫做|即)\s*(.+)$")
_DEF_BAD_TERM = re.compile(r"[不没也都很这那它谁啥什]")  # 是 is too common; reject pronoun/negation terms
_ENUM = re.compile(r"、")  # true enumeration uses 、 (not the general ，)
_SECTION_MARK = re.compile(r"^(首先|其次|然后|接着|最后|第一|第二|第三|下面|接下来|先看|再看)")
_NOTE_MARK = re.compile(r"(但|需要注意|注意|提醒|以官方为准|口径不一|存疑)")


class ScenePlanner(Protocol):
    def plan(self, beats: list[str], *, brand: str = "Monoline", date_eyebrow: str = "") -> list[dict]: ...


_TRAIL = re.compile(r"[。！？!?…；;\.]+$")

# Leading discourse markers that make poor on-slide keywords — distill skips them.
_LEAD_CONNECT = {
    "总之", "综上", "总的来说", "首先", "其次", "再次", "然后", "最后",
    "因此", "所以", "但是", "然而", "而且", "并且", "另外", "此外", "同时",
    "其实", "事实上", "例如", "比如", "也就是说", "简而言之",
}
# Short prepositional/comparative/narrative openers ("相比旧版，…" / "起初，…") that set
# up rather than carry the point — skipped only when short and followed by substance.
_SETUP_PREFIX = ("相比", "对于", "关于", "随着", "为了", "通过", "根据", "基于", "针对", "与其",
                 "起初", "后来", "随后", "于是", "接着", "从此", "那天", "那晚", "那年", "当晚", "首先")
# Short clauses ending in a temporal frame ("那晚之后", "三年以后") are lead-ins too.
_TEMPORAL_SUFFIX = ("之后", "以后", "之前", "以前", "以来")


def _is_lead_clause(p: str) -> bool:
    if p in _LEAD_CONNECT:
        return True
    if len(p) <= 6 and (p.startswith(_SETUP_PREFIX) or p.endswith(_TEMPORAL_SUFFIX)):
        return True
    return False


def distill_keyword(text: str, *, max_len: int = 12) -> tuple[str, bool]:
    """Distill a sentence to a short on-slide keyword.

    Returns (keyword, is_clean_split). is_clean_split=True when we found a natural
    clause meaningfully shorter than the full sentence → the slide shows the keyword
    and the full sentence becomes the caption. When no clean keyword exists, returns
    (full_sentence, False) → slide shows the sentence, no caption (no duplication).
    """
    s = _TRAIL.sub("", text.strip())
    parts = [p.strip() for p in re.split(r"[，、：；,;]", s) if p.strip()]
    # prefer the first clause that isn't a bare connective or short setup ("总之" / "相比旧版")
    first = next((p for p in parts if not _is_lead_clause(p)), parts[0] if parts else s)
    if 2 <= len(first) <= max_len and len(first) < len(s):
        return first, True
    if len(s) <= max_len:
        return s, False  # whole sentence is already short → title card, no caption
    return s, False


def _strip_number(sentence: str) -> str:
    s = _NUM.sub("", sentence)
    s = re.sub(r"[，,、：:\s]+$", "", s).strip("，,、：: ")
    return s


class RulePlanner:
    def plan(self, beats: list[str], *, brand: str = "Monoline", date_eyebrow: str = "") -> list[dict]:
        n = len(beats)
        scenes: list[dict] = []
        for i, b in enumerate(beats):
            if i == 0:
                scenes.append(self._title(b, brand, date_eyebrow))
            elif i == n - 1 and n > 2:
                ts = self._text_slots(b)
                scenes.append({"i": i, "kind": "summary", "source": "rules:position",
                               "slots": {"eyebrow": "In short", "headline": ts["headline"], "verbatim": ts["verbatim"]}})
            else:
                scenes.append(self._classify(i, b))
        from ..compose.icons import KIND_ICON, pick_icon
        for sc in scenes:
            icon = KIND_ICON.get(sc["kind"], "")
            if not icon:  # sparse kinds (statement/note): pick a contextual icon from the beat text
                idx = sc["i"]
                icon = pick_icon(beats[idx] if 0 <= idx < len(beats) else "")
            sc["slots"].setdefault("icon", icon)
        # V9-6: number section beats so chapter breaks read as "01 / 02 …"
        sec = 0
        for sc in scenes:
            if sc["kind"] == "section":
                sec += 1
                sc["slots"]["index"] = f"{sec:02d}"
        return scenes

    def _clean(self, s: str) -> str:
        return s.strip().rstrip("。")

    def _text_slots(self, b: str) -> dict:
        kw, clean = distill_keyword(b)
        return {"headline": kw, "verbatim": (not clean)}

    def _title(self, b: str, brand: str, date_eyebrow: str) -> dict:
        ts = self._text_slots(b)
        return {"i": 0, "kind": "title", "source": "rules:first-line",
                "slots": {"eyebrow": date_eyebrow or brand, "headline": ts["headline"], "sub": brand, "verbatim": ts["verbatim"]}}

    def _classify(self, i: int, b: str) -> dict:
        s = self._clean(b)

        # quote: whole beat wrapped in quotes
        m = _QUOTE_WRAP.match(s)
        if m:
            return {"i": i, "kind": "quote", "source": "rules:quote-wrap",
                    "slots": {"q": m.group(1), "attr": "", "verbatim": True}}

        # note: caveat markers
        if _NOTE_MARK.search(s):
            return {"i": i, "kind": "note", "source": "rules:note-mark",
                    "slots": {"marker": "!", "body": s, "verbatim": True}}

        # table: ≥2 explicit k:v pairs
        pairs = _KV.findall(s)
        if len(pairs) >= 2:
            return {"i": i, "kind": "table", "source": "rules:kv-pairs",
                    "slots": {"title": "", "rows": [{"k": k.strip(), "v": v.strip()} for k, v in pairs[:6]]}}

        # stat: a dominant number/percent/price token
        nums = [x.strip() for x in _NUM.findall(s) if any(c.isdigit() for c in x)]
        if len(nums) == 1 and len(s) <= 44:
            label = _strip_number(s) or s
            return {"i": i, "kind": "stat", "source": "rules:number",
                    "slots": {"value": nums[0], "unit": "", "label": label}}

        # definition: "X 是 Y" — but 是 is common; require a real noun term (no negation/pronoun)
        dm = _DEF.match(s)
        if dm and len(dm.group(1)) >= 2 and not _DEF_BAD_TERM.search(dm.group(1)) and len(dm.group(2)) >= 4:
            return {"i": i, "kind": "definition", "source": "rules:definition",
                    "slots": {"term": dm.group(1), "gloss": self._clean(dm.group(2))}}

        # list: true 、-enumeration of 3+ short parallel items
        if "、" in s:
            items = [x.strip() for x in _ENUM.split(s) if 2 <= len(x.strip()) <= 12]
            if len(items) >= 3:
                return {"i": i, "kind": "list", "source": "rules:enumeration",
                        "slots": {"title": "", "items": items[:5]}}

        if _SECTION_MARK.match(s):
            ts = self._text_slots(b)
            return {"i": i, "kind": "section", "source": "rules:section-mark",
                    "slots": {"title": ts["headline"], "verbatim": ts["verbatim"]}}

        # default: statement — slide shows a distilled keyword, caption carries the sentence
        ts = self._text_slots(b)
        return {"i": i, "kind": "statement", "source": "rules:default",
                "slots": {"headline": ts["headline"], "verbatim": ts["verbatim"]}}


def plan_scenes(beats: list[str], **kw: object) -> list[dict]:
    return RulePlanner().plan(beats, **kw)  # type: ignore[arg-type]
