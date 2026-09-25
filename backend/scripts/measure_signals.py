"""V49 pre-work: what layout signals actually exist in the real corpus?

Every reassignment rule we add must be grounded in text that is already there, so before
writing any rule we count how many beats carry each signal. Run with the server up:
    uv run --directory backend python scripts/measure_signals.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request

API = "http://127.0.0.1:8787"
TEST = re.compile(r"取消测试|用来撑拍数|第\d+句|测试第")

SIGNALS: dict[str, re.Pattern] = {
    # attribution → a document/quote card (poster)
    "attribution": re.compile(r"(据.{1,12}?报道|据.{1,12}?消息|发言人.{0,6}(表示|说|称)|"
                              r"(称|透露|指出|强调|表示)[，,]?\s*[“「])"),
    "quoted_clause": re.compile(r"[“「].{4,}[”」]"),
    # two named sides → compare
    "two_sides": re.compile(r"(与|和|跟|对比|相比).{1,14}(相比|而|则|更|不同)|"
                            r"(一方面|另方面|另一方面|同时).*?(另一方面|而)"),
    # enumerated pairs → cards / table
    "kv_pairs": re.compile(r"[\w一-鿿]{2,8}[：:][^。]{2,20}"),
    "ordinal_enum": re.compile(r"(一是|二是|三是|第一|第二|第三|首先|其次|最后)"),
    # a question → could be a section hook
    "question": re.compile(r"[？?]$"),
    # negation/contrast pivot
    "pivot": re.compile(r"(不是|并非|而是|不在于|关键|真正|其实|恰恰)"),
    # explicit figure of merit
    "number": re.compile(r"\d"),
    # self-reference to a picture
    "picture_ref": re.compile(r"(如图|见图|如图所示|这张图|画面里)"),
    # cause-effect chain
    "causal": re.compile(r"(因为|由于|导致|因此|从而|所以|使得)"),
    # definition shape
    "definition": re.compile(r"(是指|指的是|定义为|所谓.{1,10}[，,])"),
}


def main() -> None:
    jobs = json.load(urllib.request.urlopen(API + "/api/jobs"))
    jobs = jobs if isinstance(jobs, list) else jobs.get("jobs", [])
    beats: list[str] = []
    runs: list[tuple[str, int]] = []
    hits = {k: 0 for k in SIGNALS}
    hit_kinds = {k: {} for k in SIGNALS}
    n_scenes = 0
    for j in jobs:
        d = json.load(urllib.request.urlopen(API + "/api/jobs/" + j["id"]))
        segs = d.get("segments") or []
        if any(TEST.search(s.get("text") or "") for s in segs) or not d.get("plan"):
            continue
        beats.extend(s["text"] for s in segs)
        kinds = [s["kind"] for s in d["plan"]["scenes"]]
        n_scenes += len(kinds)
        cur, run = kinds[0], 1
        for k in kinds[1:] + ["<end>"]:
            if k == cur:
                run += 1
            else:
                runs.append((cur, run))
                cur, run = k, 1
        for s in d["plan"]["scenes"]:
            text = next((x["text"] for x in segs if x["i"] == s["i"]), "")
            for name, pat in SIGNALS.items():
                if pat.search(text or ""):
                    hits[name] += 1
                    hit_kinds[name][s["kind"]] = hit_kinds[name].get(s["kind"], 0) + 1
    total = len(beats)
    print(f"beats={total} scenes={n_scenes} jobs with plan={len(runs) and total and n_scenes}")
    print("\nsignal coverage (beats carrying the signal):")
    for name, n in sorted(hits.items(), key=lambda kv: -kv[1]):
        top = sorted(hit_kinds[name].items(), key=lambda kv: -kv[1])[:4]
        print(f"  {name:14s} {n:4d} ({n / total:.1%})  on kinds: "
              + ", ".join(f"{k}={v}" for k, v in top))
    longest = sorted(runs, key=lambda kv: -kv[1])[:12]
    print("\nlongest same-kind runs (kind, length):", longest)
    over2 = sum(1 for _, r in runs if r > 2)
    print(f"runs longer than 2: {over2}/{len(runs)}  "
          f"beats inside a run>2: {sum(r for _, r in runs if r > 2)} ({sum(r for _, r in runs if r > 2) / n_scenes:.1%})")


if __name__ == "__main__":
    sys.exit(main())
