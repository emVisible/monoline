# Documentation

Four files, each with a different shelf life. Read the **authority** column before
quoting a number out of one of them — the failure mode this folder has been burned by
is a stale count being cited as current truth.

| File | What it is | Authority |
|---|---|---|
| [`CONFIG.md`](CONFIG.md) | Every surface the tool exposes: make targets, env vars, CLI commands, all HTTP endpoints, and what is deliberately left unwired. | **Live.** A test compares it against the running app in both directions, so it cannot quietly go stale. |
| [`VISUAL.md`](VISUAL.md) | The visual element inventory plus the version ledger: one row per release, each carrying the measurement that justified it. | **Live, append-only.** This is the authoritative history of *why* the product looks like this. |
| [`PLAN.md`](PLAN.md) | The current plan, plus the **not-doing list** — approaches already falsified by measurement. | **Live but perishable.** Check the date in its header before scheduling from it. |
| [`ROADMAP.md`](ROADMAP.md) | The V1–V30 narrative. | **Frozen.** Its counts are snapshots from that era, not today's. Never cite it as current. |

## Conventions these files keep

- **A claim carries its measurement.** "Diversity improved" is not a finding; "longest
  same-kind run 15 → 2 across 311 beats" is. Numbers name their denominator.
- **A falsified idea is recorded, not deleted.** The not-doing list in `PLAN.md` exists so
  the same appealing-but-wrong lever is not rebuilt two months later. Several were.
- **English for code, Chinese for measured prose.** The ledger quotes real measurements in
  the language they were taken in; that is deliberate, not inconsistent.

## Regenerating the numbers

```bash
make test                                                     # the gate
curl -s localhost:8787/openapi.json | python3 -c "import json,sys; print(len(json.load(sys.stdin)['paths']))"
uv run --directory backend python scripts/measure_kinds.py    # which kinds are reachable
uv run --directory backend python scripts/measure_runs.py --replan   # layout diversity
```

---

# 文档说明

四份文档，「保鲜期」各不相同。引用任何数字前先看**权威性**一栏 —— 这个目录踩过的坑，
就是把一份过期快照当成了今天的真相。

- **`CONFIG.md`**：工具的全部对外面（make 目标、环境变量、CLI、所有 HTTP 端点，以及刻意
  没接线的部分）。有测试与运行中的应用**双向比对**，不可能悄悄失效。
- **`VISUAL.md`**：视觉要素清单 + 逐版台账，每行都带着「当初凭什么这么做」的实测数字。
  只追加不删改，是「产品为什么长成这样」的权威历史。
- **`PLAN.md`**：当前计划，外加**不做清单**——已被实测否掉的方向。会过期，动手前看日期。
- **`ROADMAP.md`**：V1–V30 的历史叙事。数字是**冻结快照**，不要当现状引用。

三条共同约定：**结论必须带实测**（「多样性变好了」不算，「311 拍里最长同版式连排 15→2」
才算，且数字要写明分母）；**被否掉的想法记录而非删除**（不做清单存在的意义，就是防止两个
月后有人把同一条诱人但错误的杠杆重新建一遍）；**代码注释用英文、实测叙述用中文**，这是
刻意的，不是不统一。

重测命令见上一节代码块。
