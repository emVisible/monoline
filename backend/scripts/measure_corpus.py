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


def layouts(scenes: list[dict]) -> list[tuple]:
    """A slide's visible identity is kind + treatment: two `statement`s with different
    variants do not read as a repeat, so the run metric must count them separately."""
    return [(x["kind"], (x.get("slots") or {}).get("variant")) for x in scenes]


def longest_run(keys: list) -> int:
    run = best = 1 if keys else 0
    for a, b in zip(keys, keys[1:]):
        run = run + 1 if a == b else 1
        best = max(best, run)
    return best


def count(scenes: list[dict]) -> tuple[int, int, int, int]:
    """(forbidden trailing punct, mid-clause ending, unbalanced quote, kept ？！…)"""
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
    from monoline.pipeline import planner as planner_mod
    RulePlanner = planner_mod.RulePlanner
    unbalanced: list[tuple[str, str]] = []
    punct = {"base": 0, "rot": 0}
    mid = {"base": 0, "rot": 0}
    unb = {"base": 0, "rot": 0}
    runs = {"base": 0, "rot": 0}
    runs_stored = 0
    kinds_by: dict[str, dict[str, int]] = {"base": {}, "rot": {}}
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
        runs_stored = max(runs_stored, longest_run(layouts(plan["scenes"])))
        if do_regen:
            # A/B on one variable: same beats, same rules, rotation pass off then on
            texts = [s["text"] for s in segs]
            real = planner_mod.rebalance
            planner_mod.rebalance = lambda sc, b: sc
            base = RulePlanner().plan(texts)
            planner_mod.rebalance = real
            planned = RulePlanner().plan(texts)
            for tag, scenes in (("base", base), ("rot", planned)):
                r, m, u, _ = count(scenes)
                punct[tag] = punct[tag] + r
                mid[tag] = mid[tag] + m
                unb[tag] = unb[tag] + u
                runs[tag] = max(runs[tag], longest_run(layouts(scenes)))
                for x in scenes:
                    kinds_by[tag][x["kind"]] = kinds_by[tag].get(x["kind"], 0) + 1
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
          f"mid-clause {stored[1]} ({stored[1] / n_beats:.1%}), unbalanced quotes {stored[2]}, "
          f"longest same-kind run {runs_stored}")
    if do_regen:
        for tag, label in (("base", "rules only  "), ("rot", "+ rotation  ")):
            kb = kinds_by[tag]
            tot = sum(kb.values()) or 1
            st = kb.get("statement", 0)
            top5 = sorted(kb.values(), reverse=True)[:5]
            print(f"{label}— statement {st} ({st / tot:.1%}), "
                  f"top-5 share {sum(top5) / tot:.1%}, kinds {len(kb)}/{len(REGISTRY)}, "
                  f"longest same-kind run {runs[tag]}, forbidden punct {punct[tag]}, "
                  f"mid-clause {mid[tag]}, unbalanced quotes {unb[tag]}")
    for k, t in unbalanced[:4]:
        print(f"  {k}: …{t}")


if __name__ == "__main__":
    main()
