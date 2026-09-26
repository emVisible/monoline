"""Which of the 28 presentation modes does a real job actually reach?

Run:  uv run --directory backend python scripts/measure_kinds.py [--db PATH]

Three sets, and the gaps between them are the product's real story:
  registry      what `KINDS` allows
  templates     what compose can paint            (registry − templates = a crash waiting)
  corpus        what 45 real jobs actually produced (registry − corpus = a mode nobody uses)
`source=` per kind shows whether a mode ever arrives automatically (rules/rotation/llm) or only
after a human picks it in Studio.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend" / "src"))

from monoline.ir.sceneplan import KINDS  # noqa: E402

RULE_SRC = REPO / "backend/src/monoline/pipeline/planner.py"
ROTATION_SRC = REPO / "backend/src/monoline/pipeline/rotation.py"
TEMPLATE_DIR = REPO / "backend/src/monoline/compose/templates/kinds"


def emitted_by_rules() -> set[str]:
    """Kinds the rule path can name: the planner's own verdicts plus the rotation swaps."""
    out: set[str] = set()
    for src in (RULE_SRC, ROTATION_SRC):
        text = src.read_text(encoding="utf-8")
        out |= set(re.findall(r"""["']kind["']\s*[:=]\s*["']([a-z_]+)["']""", text))
        out |= set(re.findall(r"""kind\s*=\s*["']([a-z_]+)["']""", text))
    return out


def latest_plans(conn: sqlite3.Connection) -> list[dict]:
    by_job: dict[str, str] = {}
    for jid, pj in conn.execute("SELECT job_id, plan_json FROM scene_plans ORDER BY id").fetchall():
        by_job[jid] = pj
    out = []
    for pj in by_job.values():
        try:
            out.append(json.loads(pj))
        except (TypeError, json.JSONDecodeError):
            continue
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.expanduser(
        "~/Library/Application Support/Monoline/app.db"))
    args = ap.parse_args()
    templates = {p.name.split(".")[0] for p in TEMPLATE_DIR.glob("*.html.j2")}
    rules = emitted_by_rules()
    seen: Counter[str] = Counter()
    origins: dict[str, set[str]] = {}
    plans = latest_plans(sqlite3.connect(args.db))
    for plan in plans:
        for sc in plan.get("scenes", []):
            k = sc.get("kind")
            seen[k] += 1
            origins.setdefault(k, set()).add((sc.get("source") or "?").split(":")[0])
    print(f"jobs={len(plans)}  registry={len(KINDS)}  templates={len(templates)}  "
          f"rule-reachable={len(rules)}")
    missing_tpl = sorted(set(KINDS) - templates)
    orphan_tpl = sorted(templates - set(KINDS))
    print(f"kind without a template (would crash compose): {missing_tpl or 'none'}")
    print(f"template no kind can select (dead markup):      {orphan_tpl or 'none'}")
    print("\nkind            beats  how it arrives")
    for k, n in seen.most_common():
        how = ",".join(sorted(origins[k]))
        auto = {"rules", "llm"} & origins[k]
        print(f"  {k:<14} {n:4}  {how:<14} {'自动' if auto else '只有手动'}")
    dead = sorted(set(KINDS) - set(seen))
    print(f"\nnever produced by {len(plans)} real jobs ({len(dead)} kinds): {dead}")
    for k in dead:
        print(f"  {k:<10} rule-reachable={k in rules}  has-template={k in templates}")


if __name__ == "__main__":
    main()
