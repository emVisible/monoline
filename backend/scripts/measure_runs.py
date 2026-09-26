"""How many layouts does one film actually use, and why does the rotation leave the rest as text?

Run:  uv run --directory backend python scripts/measure_runs.py [--replan]

The number this exists to answer (the user's complaint, not a vibe): 每片用了多少种版式 /
最长一段同 kind 有多少拍 / 还剩多少拍本该被 `rotation.rebalance` 换掉。

Two denominators that were wrong before they were fixed, both recorded in docs/VISUAL.md:
  · one plan per job (the newest row) — re-planned jobs used to count their beats several times;
  · `--replan` re-runs TODAY's `planner.plan_scenes()` on the stored beats. Without it the plans
    in the database were produced by a mix of code versions, and the gap it reports is history,
    not what the current rules would do (measured: stale plans show 37% of surplus beats as
    "buildable but left alone"; re-running gives 2%).

An "unswappable" surplus beat is not a bug — it is the shape of the real limit: `rotation` may
only rewrite a beat into a layout it can fill from that beat's own words, so `_ALTERNATIVES`
being small is what caps default diversity. Raising `MAX_RUN` would only make runs longer.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter
from statistics import median

from monoline.pipeline import planner
from monoline.pipeline.rotation import _ALTERNATIVES, MAX_RUN, TEXT_RUN


def latest_plans(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    by_job: dict[str, str] = {}
    for jid, pj in conn.execute("SELECT job_id, plan_json FROM scene_plans ORDER BY id"):
        by_job[jid] = pj
    out = {}
    for jid, pj in by_job.items():
        try:
            out[jid] = json.loads(pj).get("scenes", [])
        except (TypeError, json.JSONDecodeError):
            continue
    return out


def text_runs(kinds: list[str]) -> list[tuple[int, int]]:
    """Maximal runs of a plain-text kind, as (first, last) inclusive."""
    res, i = [], 0
    while i < len(kinds):
        j = i
        while j + 1 < len(kinds) and kinds[j + 1] == kinds[i]:
            j += 1
        if kinds[i] in TEXT_RUN:
            res.append((i, j))
        i = j + 1
    return res


def surplus(kinds: list[str]) -> list[int]:
    """Beat indices past MAX_RUN inside a text run — the ones rebalance is supposed to rewrite."""
    out: list[int] = []
    for a, b in text_runs(kinds):
        for off, _ in enumerate(range(a, b + 1)):
            if off + 1 > MAX_RUN:
                out.append(a + off)
    return out


def stats(kinds: list[str], beats: list[str]) -> tuple[float, int, float, int, str]:
    sur = surplus(kinds)
    blocked = [i for i in sur if not any(m(beats[i]) for m in _ALTERNATIVES)]
    return (len(set(kinds)) / len(kinds), max((b - a + 1 for a, b in text_runs(kinds)), default=0),
            kinds.count("statement") / len(kinds), len(sur),
            "无备选" if len(blocked) == len(sur) and sur else ("部分可替换" if sur else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.expanduser(
        "~/Library/Application Support/Monoline/app.db"))
    ap.add_argument("--replan", action="store_true", help="re-run today's rules on the stored beats")
    ap.add_argument("--min-beats", type=int, default=6)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    plans = latest_plans(conn)
    rows, skipped = [], 0
    for jid, sc in plans.items():
        if len(sc) < args.min_beats:
            continue
        beats = [r[0] for r in conn.execute(
            "SELECT text FROM segments WHERE job_id=? ORDER BY i", (jid,))]
        if len(beats) != len(sc):
            skipped += 1        # the segmenter changed since this plan was made — not comparable
            continue
        kinds = [s.get("kind") for s in sc]
        if args.replan:
            kinds = [s.get("kind") for s in planner.plan_scenes(beats)]
        rows.append((jid, stats(kinds, beats)))
    if not rows:
        print("没有可比作业（≥%d 拍且拍数与现存 plan 一致）" % args.min_beats)
        return

    cover = [s[0] for _, s in rows]
    print(f"作业 {len(rows)} 片  跳过（拍数与 plan 不一致）{skipped}  "
          f"{'【今天的规则重跑】' if args.replan else '【库里现存 plan，混着旧版代码】'}")
    print(f"每片 kind 覆盖：中位 {median(cover):.2f}  最差 {min(cover):.2f}  最好 {max(cover):.2f}")
    print(f"最长同 kind run：中位 {median([s[1] for _, s in rows]):.1f}  最大 {max(s[1] for _, s in rows)}")
    print(f"statement 占比：中位 {median([s[2] for _, s in rows]):.1%}")
    sur = sum(s[3] for _, s in rows)
    print(f"超出 MAX_RUN={MAX_RUN} 的拍：{sur} 拍"
          f"（其中整片都搭不出备选的作业 {Counter(s[4] for _, s in rows)['无备选']} 片）")
    print(f"轮换可选形状数 len(_ALTERNATIVES) = {len(_ALTERNATIVES)} —— 这个数就是默认多样性的弹药量")
    worst = sorted(rows, key=lambda r: -r[1][3])[:5]
    for jid, s in worst:
        if s[3]:
            print(f"  {jid[:12]}  超标 {s[3]:>2} 拍  覆盖 {s[0]:.2f}  最长 run {s[1]}  {s[4]}")


if __name__ == "__main__":
    main()
