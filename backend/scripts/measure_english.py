"""Does the per-beat model suggestion actually answer for ENGLISH beats?

Run:  uv run --directory backend python scripts/measure_english.py [--limit 6]

The first version of this probe counted `same`, and reported "landing rate 0/6, every one a
decline".  That was wrong in a way worth keeping in the ledger: `same` was inferred from
"the kind came back unchanged", which is ALSO what a dropped request and a guard-rejected answer
look like — so the count could not be read at all (one beat "answered" in 1.1s, faster than this
model decodes).  The numbers below are per-outcome (kept / changed / rejected / unanswered), and
an unanswered beat is never counted as a decline.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
from collections import Counter

from monoline.llm.client import detect
from monoline.llm.planner import suggest
from monoline.settings import Settings


def beats_for_lang(conn: sqlite3.Connection, limit: int, lang: str) -> list[tuple[str, int, str, dict]]:
    """Beats the RULES left as plain text — the only ones where "did the model redesign it?"
    has an answer.  Counting every beat would mix in kinds the model is never asked about."""
    jobs = [r[0] for r in conn.execute(
        "SELECT DISTINCT job_id FROM segments WHERE lang=? ORDER BY job_id DESC", (lang,))]
    for jid in jobs:
        rows = conn.execute(
            "SELECT plan_json FROM scene_plans WHERE job_id=? ORDER BY id DESC LIMIT 1", (jid,)).fetchone()
        if not rows:
            continue
        kinds = {s["i"]: s for s in json.loads(rows[0]).get("scenes", [])
                 if s.get("kind") == "statement"}
        segs = conn.execute("SELECT i, text FROM segments WHERE job_id=? ORDER BY i", (jid,)).fetchall()
        picked = [(jid, i, t, kinds[i]) for i, t in segs if i in kinds][:limit]
        if picked:
            print(f"{lang} job {jid}: {len(picked)} plain-text beats of "
                  f"{sum(1 for _ in segs if _[0] in kinds)} in this script")
            return picked
    print(f"no {lang} job with a plan in this database")
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.expanduser(
        "~/Library/Application Support/Monoline/app.db"))
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--lang", default="en", help="segments.lang, e.g. en or zh")
    args = ap.parse_args()

    beats = beats_for_lang(sqlite3.connect(args.db), args.limit, args.lang)
    if not beats:
        return
    s = Settings()
    t = detect(s)
    print(f"target: {t.model} ok={t.ok}")
    seen: Counter[str] = Counter()
    for _, i, text, scene in beats:
        v = asyncio.run(suggest(s, text, scene, target=t, use_cache=False))
        seen[v["status"]] += 1
        extra = v["error"] or (v["why"][0] if v["why"] else "")
        print(f"  #{i:>2} {v['status']:<11} {str(v['kind'] or ''):<9} "
              f"{v['seconds']:>6}s  {text[:34]!r} {extra[:60]}")
    asked = sum(seen.values())
    answered = asked - seen["unanswered"]
    print(f"\nasked={asked} answered={answered} → {dict(seen)}")
    if answered:
        print(f"landing rate among ANSWERED beats: {seen['changed']}/{answered} "
              f"= {seen['changed'] / answered:.0%}")
    else:
        print("landing rate undefined: the model answered none of these beats")


if __name__ == "__main__":
    main()
