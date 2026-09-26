"""V29: a local model upgrades only the beats the rules could not do anything with.

Why not "the LLM plans everything" — measured on the local 7.5B q4 model:
a full-plan request cost 83s, returned 5 items for 6 beats (breaking the
1 beat = 1 scene invariant), reshaped slots (`stat` came back as `{"stat":[…]}`),
and still classified an arrow chain and a "分为四层" enumeration as plain `list` —
which the rule planner now renders as real flow / radial diagrams. So the rules own
the structure and the model is asked only about beats that would otherwise be one
line of text, and its answer is dropped unless it is well-formed and grounded.
"""
from __future__ import annotations

import re

from .client import LLMError, Target, chat, detect, list_as, parse_json
from ..pipeline.display_text import tidy_slots

# What the model may promote a plain sentence INTO. Deliberately excludes title /
# summary / section (positional), note (rules own caveats) and image (needs an upload).
ALLOWED: dict[str, dict[str, str]] = {
    "stat": {"value": "s", "label": "s"},
    "definition": {"term": "s", "gloss": "s"},
    "quote": {"q": "s"},
    "list": {"items": "sl"},
    "table": {"rows": "kv"},
    "bars": {"title": "s", "rows": "kv"},
    "kpi": {"title": "s", "rows": "kv"},
    "timeline": {"title": "s", "rows": "kv"},
    "share": {"title": "s", "rows": "kv"},
    "trend": {"title": "s", "series": "sl"},
    "matrix": {"title": "s", "x_axis": "s", "y_axis": "s", "cells": "sl"},
    "cards": {"title": "s", "rows": "kv"},
    "compare": {"a": "pair", "b": "pair"},
    "flow": {"nodes": "sl"},
    "radial": {"hub": "s", "nodes": "sl"},
    "steps": {"steps": "sl"},
}

_MAX_STR, _MIN_ITEMS, _MAX_ITEMS = 24, 2, 5
# A local model gets both worse and heavier with a long list: it returns fewer items than
# asked (breaking 1 beat = 1 scene) and a big prompt is what pushes the host out of memory.
# So the weak beats go up in sequential batches under both budgets.
BATCH_BEATS = 12
BATCH_CHARS = 900
# Beats whose rule verdict is "just text" — the only ones worth asking about.
WEAK_KINDS = {"statement"}
_PUNCT = re.compile(r"[\s，,。.、：:；;！!？?“”\"'『」（）()《》\-—→…·*_#>❶-❿]")
# A slot that ends on a copula/particle is the sentence cut in half ("…的核心是"), which
# reads as a bug on screen even though every character is faithfully from the beat.
_DANGLING = re.compile(r"[是为指把将而且的和在与就都很这那的了着吗呢啊吧]$")

# Slot types described as the literal JSON the model must produce. Describing them in prose
# ("rows=k:v对象数组") was measured to be the failure: a 4B model returns `cards` with only
# `title` filled because nothing in the prompt shows that `rows` exists next to it.
_SHAPE = {"s": '"…"', "sl": '["…", "…"]', "kv": '[{"k": "…", "v": "…"}]',
          "pair": '{"h": "…", "d": "…"}'}

_SPEC_LINES = "\n".join(
    f'{k}: {{' + ", ".join(f'"{name}": {_SHAPE[t]}' for name, t in spec.items()) + '}'
    for k, spec in ALLOWED.items()
)


def build_prompt(items: list[tuple[int, str]]) -> list[dict]:
    sys = (
        "你是中文短视频的分镜判定器。给你若干「拍」（一句口播），逐拍判断它最适合画成什么，"
        "并抽取画面要用的文字。\n"
        f"可选类型与槽位：\n{_SPEC_LINES}\n"
        "硬性要求：\n"
        # json_object mode wants ONE top-level object — asking for a bare array makes
        # Ollama emit a single item and stop, which reads as "everything rejected".
        "1) 只输出一个 JSON 对象：{\"scenes\":[{\"i\":序号,\"kind\":类型,\"slots\":{…}}, …]}，不要解释、不要代码块；\n"
        "2) scenes 数组长度等于拍数，序号照抄；\n"
        "3) slots 必须把该类型上面那一行的每个键都填上，缺任何一个键该条即作废；\n"
        "4) 槽位里的每个字都必须原样来自该拍（可截取，不可改写、不可新增）；\n"
        f"5) 每个字符串不超过 {_MAX_STR} 个显示单元（≈{_MAX_STR} 个汉字 = ≈{_MAX_STR * 2} 个英文字母"
        f" ≈ {max(1, _MAX_STR // 3)} 个英文单词）；数组类槽位 {_MIN_ITEMS}-{_MAX_ITEMS} 项；\n"
        "6) 如果某拍确实不适合上面任何类型，输出 {\"i\":序号,\"kind\":\"statement\",\"slots\":{}}。"
    )
    user = "\n".join(f"{i}. {text}" for i, text in items)
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def _norm(s: str) -> str:
    return _PUNCT.sub("", s or "")


def _width(s: str) -> float:
    """Display units, not characters: a CJK glyph is one, a latin glyph about half.

    The cap is a slide-fit rule, and `len()` measured it in characters — so a 24-unit budget
    allowed 24 Chinese characters but only ~12 English words' worth of *text*, while the prompt
    said 「不超过 24 字」 and a model reading English counts 字 as **words**. Measured on an
    English script: the model's single non-statement verdict was a 51-char quote, rejected as
    "too long" when it is 25.5 units — the two sides were not using the same ruler.
    """
    return sum(1.0 if "一" <= c <= "鿿" else 0.5 for c in s)


def _grounded(value: str, beat: str) -> bool:
    """Reject invented copy — a small model will happily write a nicer phrase — and a
    value that ends mid-sentence, which is grounded but reads as a truncation bug."""
    v, b = _norm(value), _norm(beat)
    return bool(v) and _width(v) <= _MAX_STR and v in b and not _DANGLING.search(v)


def _clean_slots(kind: str, slots: object, beat: str) -> dict | None:
    """Validate + normalize one verdict. None = unusable, keep the rule's answer."""
    if not isinstance(slots, dict):
        return None
    out: dict = {}
    for name, typ in ALLOWED[kind].items():
        raw = slots.get(name)
        if typ == "s":
            val = str(raw or "").strip()
            if not _grounded(val, beat):
                return None
            out[name] = val
        elif typ == "sl":
            items = [str(x).strip() for x in (list_as(raw) or []) if str(x).strip()]
            if not (_MIN_ITEMS <= len(items) <= _MAX_ITEMS) or not all(_grounded(x, beat) for x in items):
                return None
            out[name] = items[:_MAX_ITEMS]
        elif typ == "kv":
            rows = []
            for r in list_as(raw) or []:
                if not isinstance(r, dict):
                    return None
                k, v = str(r.get("k", "")).strip(), str(r.get("v", "")).strip()
                if not (_grounded(k, beat) and _grounded(v, beat)):
                    return None
                rows.append({"k": k, "v": v})
            if not (_MIN_ITEMS <= len(rows) <= _MAX_ITEMS):
                return None
            out[name] = rows
        elif typ == "pair":
            h = str((raw or {}).get("h", "")).strip() if isinstance(raw, dict) else ""
            d = str((raw or {}).get("d", "")).strip() if isinstance(raw, dict) else ""
            if not (_grounded(h, beat) and _grounded(d, beat)):
                return None
            out[name] = {"h": h, "d": d}
    return out


def merge(beats: list[str], scenes: list[dict], payload: object) -> tuple[list[dict], dict]:
    """Fold validated model verdicts into the rule plan. Never changes the scene count.

    `rejected` used to cover three different facts, which is how a working feature looked
    broken: measured on a real 15-beat script, 4 runs all reported `upgraded=0 rejected=15`,
    and 13 of those 15 were the model correctly saying "this one stays plain text". Now the
    three are counted apart — `declined` (the model agrees with the rules: a verdict, not a
    failure), `bad_kind` (it named a type we never offered) and `bad_slots` (it named one it
    could not fill — e.g. `cards` with a title and no rows, which is what the 4B model does
    most often). `why` carries one example so the number can be read without re-running.
    """
    stats = {"asked": 0, "upgraded": 0, "declined": 0, "bad_kind": 0, "bad_slots": 0}
    by_index = {}
    for item in list_as(payload):
        if isinstance(item, dict) and isinstance(item.get("i"), int):
            by_index[item["i"]] = item
    out = list(scenes)
    for i, beat in enumerate(beats):
        if out[i]["kind"] not in WEAK_KINDS:
            continue
        stats["asked"] += 1
        verdict = by_index.get(i)
        kind = (verdict or {}).get("kind") if verdict else None
        if kind == out[i]["kind"]:                  # "leave it as text" is an answer
            stats["declined"] += 1
            continue
        if kind not in ALLOWED:
            stats["bad_kind"] += 1
            stats.setdefault("why", []).append(f"#{i} kind={kind!r} 不在候选类型里")
            continue
        slots = _clean_slots(kind, (verdict or {}).get("slots"), beat)
        if slots is None:
            stats["bad_slots"] += 1
            stats.setdefault("why", []).append(
                f"#{i} {kind} 槽位填不上（要 {'/'.join(ALLOWED[kind])}，给了 "
                f"{sorted((verdict or {}).get('slots') or {})}）")
            continue
        out[i] = {"i": i, "kind": kind, "source": "llm:upgrade",
                  "slots": tidy_slots(kind, slots)}
        stats["upgraded"] += 1
    if isinstance(stats.get("why"), list):
        stats["why"] = stats["why"][:3]
    stats["rejected"] = stats["bad_kind"] + stats["bad_slots"]
    return out, stats


def _batches(items: list[tuple[int, str]], *, beats: int = BATCH_BEATS,
             chars: int = BATCH_CHARS) -> list[list[tuple[int, str]]]:
    """Group weak beats into requests under BOTH budgets, preserving order. A single beat
    longer than the char budget still gets its own batch (never dropped)."""
    out: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    used = 0
    for item in items:
        if cur and (len(cur) >= beats or used + len(item[1]) > chars):
            out.append(cur)
            cur, used = [], 0
        cur.append(item)
        used += len(item[1])
    if cur:
        out.append(cur)
    return out


async def upgrade(settings, beats: list[str], scenes: list[dict], *,
                  target: Target | None = None, timeout: float = 240.0) -> tuple[list[dict], dict]:
    """Ask the model about the weak beats. Returns (scenes, stats); never raises."""
    idx = [(i, beats[i]) for i in range(len(beats)) if scenes[i]["kind"] in WEAK_KINDS]
    t = target or detect(settings)
    if not idx or not t.ok:
        return scenes, {"asked": len(idx), "upgraded": 0, "rejected": 0, "skipped": "no target" if not t.ok else "no weak beats"}
    # the budgets are per-model: a small local context wants smaller batches
    batches = _batches(idx, beats=max(1, int(getattr(settings, "llm_batch_beats", BATCH_BEATS) or 1)),
                       chars=max(60, int(getattr(settings, "llm_batch_chars", BATCH_CHARS) or 0)))
    rows: list[dict] = []
    failed: list[str] = []
    for b in batches:
        try:
            rows.extend(list_as(parse_json(await chat(
                build_prompt(b), target=t, temperature=0.0, json_mode=True, timeout=timeout))))
        except (LLMError, ValueError, TypeError) as e:
            # One bad batch costs its own beats only — the rest keep their upgrades and the
            # rule plan is never replaced by an empty one.
            failed.append(str(e)[:120])
    out, stats = merge(beats, scenes, rows)
    stats.update({"model": t.model, "batches": len(batches), "failed_batches": len(failed)})
    if failed:
        stats["error"] = failed[0]
    return out, stats
