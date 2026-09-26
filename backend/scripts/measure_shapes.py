"""Corpus audit for the one lever the rules still cannot pull: does a plain-text beat actually
carry a rhetorical shape (对比 / 因果 / 跨度 / 序数) that a rule could promote into a diagram?

Run:  uv run --directory backend python scripts/measure_shapes.py [--db PATH]

Denominator rules that cost me a wrong conclusion when I first skipped them:
  · one plan per job (the newest row) — a job re-planned three times used to count its beats thrice;
  · development scripts filtered out — the synthetic 「这是第N句用来撑拍数」稿 inflate every pattern.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict

DEV = ("用来撑拍数", "这是第", "取消测试", "第N拍", "开场介绍", "测试语音")
# Shapes a rule could plausibly turn into a diagram, and which kind it would map to.
SHAPES: dict[str, tuple[str, re.Pattern[str]]] = {
    "对比 不是…而是 / A而B": ("compare", re.compile(r"不是[^，。]{1,14}[，、](而|是)|[，、]而是")),
    "跨度 从…到…": ("steps", re.compile(r"从[^，。到]{1,12}[到至][^，。]{1,12}")),
    "因果 因为…所以 / 导致": ("flow", re.compile(r"因为[^，。]{2,}[，](所以|就|才)|导致|使得|因而|因此|所以")),
    "序数列举 第一 / 一是": ("steps", re.compile(r"(?:^|[，、\s])(?:第[一二三四五六七八九十]|[一二三四五六七八九][是、])")),
    "条件 只要…就 / 只有…才": ("flow", re.compile(r"只要[^，。]{2,}[，](就|才)|只有[^，。]{2,}[，]才|一旦")),
}


def latest_plans(conn: sqlite3.Connection) -> list[dict]:
    """The newest plan row per job. scene_plans.id is AUTOINCREMENT, so MAX(id) is the latest."""
    rows = conn.execute("SELECT job_id, plan_json, id FROM scene_plans ORDER BY id").fetchall()
    by_job: dict[str, str] = {}
    for jid, pj, _ in rows:
        by_job[jid] = pj
    out = []
    for pj in by_job.values():
        try:
            out.append(json.loads(pj))
        except (TypeError, json.JSONDecodeError):
            continue
    return out


def statement_beats(plans: list[dict]) -> list[str]:
    texts: list[str] = []
    for plan in plans:
        for sc in plan.get("scenes", []):
            if sc.get("kind") != "statement":
                continue
            t = ((sc.get("slots") or {}).get("headline") or "").strip()
            if t and not any(d in t for d in DEV):
                texts.append(t)
    return texts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.expanduser(
        "~/Library/Application Support/Monoline/app.db"))
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    plans = latest_plans(conn)
    all_kinds = Counter(sc.get("kind") for p in plans for sc in p.get("scenes", []))
    stmts = statement_beats(plans)
    n_all = sum(all_kinds.values())
    print(f"jobs with a plan: {len(plans)}   beats: {n_all}   "
          f"statement beats: {len(stmts)} ({len(stmts) / max(1, n_all):.1%})")
    share = [len(set(sc.get("kind") for sc in p["scenes"])) / len(p["scenes"])
             for p in plans if len(p.get("scenes", [])) >= 6]
    if share:
        share.sort()
        print(f"distinct kinds per job (≥6 beats, median): {share[len(share) // 2]:.2f}")
    print("\nrhetorical shapes still sitting in plain text:")
    hits: dict[str, list[str]] = defaultdict(list)
    for name, (_kind, rx) in SHAPES.items():
        matched = [t for t in stmts if rx.search(t)]
        hits[name] = sorted(set(matched))
        pct = len(matched) / max(1, len(stmts))
        print(f"  {name}: {len(matched)} 拍 = {pct:.1%}（唯一句子 {len(set(matched))}）")
    print("\n每类唯一句子（决定它值不值得写成一条规则）：")
    for name, uniq in hits.items():
        print(f"  {name}: {len(uniq)}")
        for t in uniq[:3]:
            print(f"     · {t[:56]}")


if __name__ == "__main__":
    main()
