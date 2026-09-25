"""Reproduce the numbers in docs/PLAN.md against the live job library.

Read-only: it queries the running app's API and prints counts. Run with the server up:
    uv run --directory backend python scripts/measure_corpus.py
"""
from __future__ import annotations

import json
import re
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
TRAIL = re.compile(r"[，。、：；！？,.;:!?]$")
MIDCLAUSE = re.compile(r"[，、：；,]$")


def get(path: str) -> dict:
    with urllib.request.urlopen(API + path, timeout=30) as f:
        return json.loads(f.read())


def main() -> None:
    jobs = get("/api/jobs")
    jobs = jobs if isinstance(jobs, list) else jobs.get("jobs", [])
    kinds: dict[str, int] = {}
    used: set[str] = set()
    n_jobs = n_beats = 0
    chars: list[int] = []
    trail: list[tuple[str, str]] = []
    mid: list[tuple[str, str]] = []
    unbalanced: list[tuple[str, str]] = []
    for j in jobs:
        d = get("/api/jobs/" + j["id"])
        if any(TEST.search(s.get("text") or "") for s in (d.get("segments") or [])):
            continue
        plan = d.get("plan")
        if not plan:
            continue
        n_jobs += 1
        n_beats += len(plan["scenes"])
        chars.append(sum(len(s.get("text") or "") for s in (d.get("segments") or [])))
        for s in plan["scenes"]:
            kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
            used.add(s["kind"])
            for f in FIELDS:
                v = (s.get("slots") or {}).get(f)
                if not isinstance(v, str) or not v.strip():
                    continue
                t = v.strip()
                if TRAIL.search(t):
                    trail.append((s["kind"], t[-16:]))
                if MIDCLAUSE.search(t):
                    mid.append((s["kind"], t[-16:]))
                if t.count("“") != t.count("”"):
                    unbalanced.append((s["kind"], t[:32]))
    top = sorted(kinds.items(), key=lambda kv: -kv[1])
    print(f"real jobs={n_jobs}  beats={n_beats}  chars min/median/max="
          f"{min(chars)}/{sorted(chars)[len(chars) // 2]}/{max(chars)}")
    print(f"kinds used {len(used)}/{len(REGISTRY)}  never used: {[k for k in REGISTRY if k not in used]}")
    print("distribution: " + ", ".join(f"{k} {v} ({v / n_beats:.1%})" for k, v in top))
    print(f"top-5 share {sum(v for _, v in top[:5]) / n_beats:.1%}")
    print(f"display text ending in punctuation: {len(trail)} ({len(trail) / n_beats:.1%})")
    print(f"  of which ending mid-clause (，、：；): {len(mid)} ({len(mid) / n_beats:.1%})")
    print(f"unbalanced quote displays: {len(unbalanced)}")
    for k, t in unbalanced[:4]:
        print(f"  {k}: …{t}")


if __name__ == "__main__":
    main()
