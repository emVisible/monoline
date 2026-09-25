"""Reproduce the numbers in docs/PLAN.md against the live job library.

Read-only: it queries the running app's API and prints counts. Run with the server up:
    uv run --directory backend python scripts/measure_corpus.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request

API = "http://127.0.0.1:8787"
# the author's own dev/test scripts, which would otherwise dominate every ratio
TEST = re.compile(r"取消测试|用来撑拍数|第\d+句|测试第")
REGISTRY = ["title", "statement", "section", "definition", "stat", "table", "cards", "compare",
            "quote", "list", "note", "summary", "image", "flow", "radial", "steps", "arch",
            "cycle", "funnel", "bars", "kpi", "timeline", "share", "trend", "matrix", "poster",
            "showcase"]
# every slot a template can put on screen as display text
FIELDS = ("headline", "title", "q", "body", "label", "term", "gloss", "sub", "hub", "tagline")
# GB/T forbids these at the end of a display line; ？ ！ … are kept on purpose
TRAIL = re.compile(r"[，。、：；,;]$")
KEPT = re.compile(r"[？！…?!]$")
MIDCLAUSE = re.compile(r"[，、：；,]$")


def get(path: str) -> dict:
    with urllib.request.urlopen(API + path, timeout=30) as f:
        return json.loads(f.read())


def count(scenes: list[dict]) -> tuple[int, int, int]:
    """(ends-in-punctuation, ends-mid-clause, unbalanced-quote) over every display slot."""
    trail = mid = unbal = kept = 0
    for s in scenes:
        for f in FIELDS:
            v = (s.get("slots") or {}).get(f)
            if not isinstance(v, str) or not v.strip():
                continue
            t = v.strip()
            if TRAIL.search(t):
                trail += 1
            if KEPT.search(t):
                kept += 1
            if MIDCLAUSE.search(t):
                mid += 1
            if t.count("“") != t.count("”"):
                unbal += 1
    return trail, mid, unbal, kept


def main() -> None:
    jobs = get("/api/jobs")
    jobs = jobs if isinstance(jobs, list) else jobs.get("jobs", [])
    kinds: dict[str, int] = {}
    used: set[str] = set()
    n_jobs = n_beats = 0
    chars: list[int] = []
    stored = [0, 0, 0]
    regen = [0, 0, 0]
    do_regen = "--regen" in sys.argv
    if do_regen:
        from monoline.pipeline.planner import RulePlanner
    unbalanced: list[tuple[str, str]] = []
    for j in jobs:
        d = get("/api/jobs/" + j["id"])
        segs = d.get("segments") or []
        if any(TEST.search(s.get("text") or "") for s in segs):
            continue
        plan = d.get("plan")
        if not plan:
            continue
        n_jobs += 1
        n_beats += len(plan["scenes"])
        chars.append(sum(len(s.get("text") or "") for s in segs))
        a, b, c, _ = count(plan["scenes"])
        stored[0] += a
        stored[1] += b
        stored[2] += c
        if do_regen:
            r, m, u, _ = count(RulePlanner().plan([s["text"] for s in segs]))
            regen[0] += r
            regen[1] += m
            regen[2] += u
        for s in plan["scenes"]:
            kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
            used.add(s["kind"])
            for f in FIELDS:
                v = (s.get("slots") or {}).get(f)
                if isinstance(v, str) and v.strip() and v.count("“") != v.count("”"):
                    unbalanced.append((s["kind"], v[:32]))
    top = sorted(kinds.items(), key=lambda kv: -kv[1])
    print(f"real jobs={n_jobs}  beats={n_beats}  chars min/median/max="
          f"{min(chars)}/{sorted(chars)[len(chars) // 2]}/{max(chars)}")
    print(f"kinds used {len(used)}/{len(REGISTRY)}  never used: {[k for k in REGISTRY if k not in used]}")
    print("distribution: " + ", ".join(f"{k} {v} ({v / n_beats:.1%})" for k, v in top))
    print(f"top-5 share {sum(v for _, v in top[:5]) / n_beats:.1%}")
    print(f"STORED plan  — forbidden trailing punct {stored[0]} ({stored[0] / n_beats:.1%}), "
          f"mid-clause {stored[1]} ({stored[1] / n_beats:.1%}), unbalanced quotes {stored[2]}")
    if do_regen:
        print(f"RE-PLANNED   — forbidden trailing punct {regen[0]}, mid-clause {regen[1]}, "
              f"unbalanced quotes {regen[2]}")
    for k, t in unbalanced[:4]:
        print(f"  {k}: …{t}")


if __name__ == "__main__":
    main()
