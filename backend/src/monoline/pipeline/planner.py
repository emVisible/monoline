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

# ── V27: content that should render as a diagram (nodes + connectors), not as text ──
# Longest arrow spellings first so "-->" can't be re-split by "->".
_ARROW = re.compile(r"→|⇒|➜|➦|--+>|=>|->")
# "X 分为 A、B、C" / "X 包括以下三个模块：A、B、C" — a head term that owns a list.
_RADIAL = re.compile(
    r"^(.{2,14}?)(?:主要|大致|一共)?(分为|包括|涵盖|包含|划分为|由|分别是|涉及|覆盖)"
    r"(?:以下|如下|这)?[一二三四五六七八九十\d]{0,3}"
    r"(?:个|项|类|种|部分|方面|环节|步骤|维度|模块)?\s*[:：]?\s*(.+)$"
)
_STEP_MARK = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩]|第\s*[一二三四五六七八九十1-9]\s*[步次阶段期]")
# A "标题：" lead-in that names the diagram rather than being one of its parts.
_LEAD_LABEL = re.compile(r"^([^，,。；;]{2,10}?)\s*[:：]\s*(.+)$")


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


def _flow_nodes(s: str) -> tuple[str, list[str]]:
    """'流程：A→B→C' → ('流程', [A,B,C]). Empty unless it's a real chain of ≥3 short,
    self-contained nodes — a bare "0→1" range or a numeric span isn't a diagram."""
    parts = [p.strip(" \t") for p in _ARROW.split(s)]
    if len(parts) < 3:
        return "", []
    title = ""
    lead = _LEAD_LABEL.match(parts[0])
    if lead:
        title, parts[0] = lead.group(1).strip(), lead.group(2).strip()
    nodes = [p for p in parts if p]
    if len(nodes) < 3 or any(len(x) > 14 or re.search(r"[、，,。；;]", x) for x in nodes):
        return "", []
    return title, nodes[:6]


def _radial(s: str) -> tuple[str, list[str]]:
    """'系统分为感知、决策、执行三层' → ('系统', [感知,决策,执行三层]). A head term that
    owns an enumeration is the hub; the enumeration items are its branches."""
    m = _RADIAL.match(s)
    if not m:
        return "", []
    term, tail = m.group(1).strip(), m.group(3)
    items = [x.strip(" \t") for x in (re.split(r"、", tail) if "、" in tail else re.split(r"[，,]", tail))]
    items = [_TAIL_COUNT.sub("", x).strip(" ，,、的") for x in items]
    items = [x for x in items if 2 <= len(x) <= 10]
    if len(items) < 3:
        return "", []
    return term, items[:5]


def _steps(s: str) -> tuple[str, list[str]]:
    """'节奏：①调研 ②试点 ③推广' / '第一步…第二步…' → a numbered timeline."""
    marks = list(_STEP_MARK.finditer(s))
    if len(marks) < 2:
        return "", []
    head = re.sub(r"\s*[:：]\s*$", "", s[:marks[0].start()].strip(" ，,。"))
    title = head if 2 <= len(head) <= 14 else ""
    out: list[str] = []
    for idx, m in enumerate(marks):
        end = marks[idx + 1].start() if idx + 1 < len(marks) else len(s)
        body = s[m.end():end].strip(" ，,、：:；;")
        if not body or len(body) > 18 or "。" in body:
            return "", []
        out.append(body)
    return title, out[:5]


def apply_icons(scenes: list[dict], beats: list[str]) -> None:
    """Give every scene an icon (kind default, else picked from its beat). In-place, and
    re-run after an LLM upgrade so a promoted beat doesn't keep the old kind's icon."""
    from ..compose.icons import KIND_ICON, pick_icon
    for sc in scenes:
        icon = KIND_ICON.get(sc["kind"], "")
        if not icon:  # sparse kinds (statement/note): pick a contextual icon from the beat text
            idx = sc["i"]
            icon = pick_icon(beats[idx] if 0 <= idx < len(beats) else "")
        sc["slots"]["icon"] = icon


def number_sections(scenes: list[dict]) -> None:
    """V9-6: number section beats so chapter breaks read as "01 / 02 …"."""
    sec = 0
    for sc in scenes:
        if sc["kind"] == "section":
            sec += 1
            sc["slots"]["index"] = f"{sec:02d}"



# ── V30: numeric ladders, closed loops and layer stacks ─────────────────────────
_NUMV = re.compile(r"^[-+]?[\d.,]+\s*(%|％|倍|万|亿|千|人|次|元|块|户|家|台|单|ms|s|秒|分钟|小时|天|周|月|年|[KMGB]|GB|Token|token)?$")
_LOOP_MARK = re.compile(r"(循环|闭环|反馈环|周而复始|反复|回流|飞轮|雪球|正循环)")
# "…监控四层" — the count belongs to the sentence, not to the last node's name.
_TAIL_COUNT = re.compile(r"[一二三四五六七八九十\d]+(层|个|项|种|部分|方面|模块|环节|步骤|维度|级)$")
_LAYER_MARK = re.compile(r"([一二三四五六七八九十\d]层|分层|堆叠|层次|底层|顶层|中层)")


def _numeric(v: str) -> bool:
    return bool(_NUMV.match((v or "").strip()))


_STEP = re.compile(r"^(\S{1,6}?)\s*[：:]?\s*([-+]?[\d.,]+\s*\S{0,3})$")


def _cycle_nodes(s: str) -> tuple[str, list[str]]:
    """'A→B→C→A' (or a loop word + an arrow chain) → a ring. The repeated closing node
    is dropped: the arc back to the start is drawn by the template, not listed twice."""
    parts = [x.strip(" \t") for x in _ARROW.split(s)]
    if len(parts) < 3:
        return "", []
    title = ""
    lead = _LEAD_LABEL.match(parts[0])
    if lead:
        title, parts[0] = lead.group(1).strip(), lead.group(2).strip()
    nodes = [x for x in parts if x and not re.search(r"[、，,。；;]", x)]
    if len(nodes) < 3 or any(len(x) > 12 for x in nodes):
        return "", []
    head, tailn = _norm_node(nodes[0]), _norm_node(nodes[-1])
    returns = head == tailn or (len(head) >= 2 and (head in tailn or tailn in head))
    if not (returns or _LOOP_MARK.search(s)):
        return "", []
    if returns:
        nodes = nodes[:-1]
    return title, nodes[:6]


def _norm_node(x: str) -> str:
    return re.sub(r"[\s的]", "", x or "")


def _layers(s: str) -> tuple[str, list[str]]:
    """'平台分为接入、服务、存储三层' → a stack, not a mind map: the word 层 says the
    items sit on top of each other."""
    if not _LAYER_MARK.search(s):
        return "", []
    rt, rnodes = _radial(s)
    if not rnodes:
        return "", []
    return rt, rnodes


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
        apply_icons(scenes, beats)
        number_sections(scenes)
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

        # funnel: ≥3 numeric pairs (k:v or "词 数字") is a conversion ladder, not a table
        if len(pairs) >= 3 and all(_numeric(v) for _k, v in pairs):
            ft = _LEAD_LABEL.match(s)
            return {"i": i, "kind": "funnel", "source": "rules:numeric-ladder",
                    "slots": {"title": (ft.group(1).strip() if ft else ""),
                              "stages": [{"k": k.strip(), "v": v.strip()} for k, v in pairs[:5]],
                              "verbatim": True}}
        lt, lst = _ladder_stages(s)
        if lst:
            return {"i": i, "kind": "funnel", "source": "rules:numeric-ladder",
                    "slots": {"title": lt, "stages": lst, "verbatim": True}}

        # cycle: a closed arrow chain is a ring, not a line
        ct, cnodes = _cycle_nodes(s)
        if cnodes:
            return {"i": i, "kind": "cycle", "source": "rules:closed-loop",
                    "slots": {"title": ct, "nodes": cnodes, "verbatim": True}}

        # arch: "…三层" is a stack; without the layer word it stays a mind map
        at, alayers = _layers(s)
        if alayers:
            return {"i": i, "kind": "arch", "source": "rules:layer-stack",
                    "slots": {"title": at, "layers": alayers, "verbatim": True}}

        # V27 flow: an arrow chain renders as connected nodes, not as a sentence.
        # Ahead of `stat` so "效率翻3倍→周期砍半→成本降三成" isn't reduced to one number.
        ft, fnodes = _flow_nodes(s)
        if fnodes:
            return {"i": i, "kind": "flow", "source": "rules:arrow-chain",
                    "slots": {"title": ft, "nodes": fnodes, "verbatim": True}}

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

        # V27 radial: a hub term owning an enumeration → mind-map (center + branches).
        rt, rnodes = _radial(s)
        if rnodes:
            return {"i": i, "kind": "radial", "source": "rules:hub-enumeration",
                    "slots": {"hub": rt, "nodes": rnodes, "verbatim": True}}

        # V27 steps: inline ordinals (①②③ / 第一步…) → numbered timeline
        st, ssteps = _steps(s)
        if ssteps:
            return {"i": i, "kind": "steps", "source": "rules:ordinal-chain",
                    "slots": {"title": st, "steps": ssteps, "verbatim": True}}

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


def _ladder_stages(s: str) -> tuple[str, list[dict]]:
    lead = _LEAD_LABEL.match(s)
    body = lead.group(2) if lead else s
    parts = [x.strip() for x in re.split(r"、|[，,]", body) if x.strip()]
    stages: list[dict] = []
    for x in parts:
        m = _STEP.match(x)
        if m:
            stages.append({"k": m.group(1).strip(" ：:"), "v": m.group(2).strip()})
    if len(stages) < 3 or (lead and len(lead.group(1)) > 10):
        return "", []
    return (lead.group(1).strip() if lead else ""), stages[:5]
