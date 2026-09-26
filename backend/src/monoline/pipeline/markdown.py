"""Markdown BLOCK syntax the beat model has no container for, rewritten into lines it reads.

The IR guarantees 1 beat = 1 segment = 1 scene (the audio is cut from the beat), so a table —
one thought spread over N rows — cannot become N scenes, and it must not reach the narration
as `| 波长 | 穿透 |` either. Measured on a real paste: a GFM table produced four beats full of
pipes, one of them `--- ---`, and the TTS stage answered `rc=1`, failing the whole job.

So a table collapses into the one line shape the planner already knows how to draw: k：v pairs
(→ bars / kpi / table scene). A thematic break (`---`) carries no words at all and is dropped.

Parsed with markdown-it, not regexes, because `---` under a paragraph is a setext heading and
`|` inside a paragraph is not a table — guessing there would silently eat a sentence.
"""
from __future__ import annotations

from markdown_it import MarkdownIt

_MD = MarkdownIt("commonmark").enable("table")

# A header whose first cell just names the column ("项 / 名称 / name") is not data: the row
# below it is already self-describing. Any other first cell (温度, 指标) is a real key, and a
# single-row table is read column-wise — 温度：20℃，压力：1atm — rather than 20℃：1atm.
_FIELD_HEADER = {"项", "项目", "条目", "名称", "名字", "指标", "参数", "类别", "分类", "维度",
                 "字段", "key", "name", "item", "label", "field"}


def _table_rows(tokens: list, start: int) -> tuple[list[list[str]], int]:
    """Cells of every row of the table that opens at `tokens[start]`, and the index of its
    closing token (the delimiter row never appears, so rows[0] is always the header)."""
    rows: list[list[str]] = []
    cells: list[str] | None = None
    for j in range(start + 1, len(tokens)):
        tok = tokens[j]
        if tok.type == "table_close":
            return rows, j
        if tok.type == "tr_open":
            cells = []
            rows.append(cells)
        elif tok.type == "inline" and cells is not None:
            cells.append(tok.content.strip())
    return rows, len(tokens)


def _table_line(rows: list[list[str]]) -> str:
    rows = [[c.strip() for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    head, data = rows[0], rows[1:] or rows
    if max((len(r) for r in data), default=0) <= 1:
        return "、".join(r[0] for r in data if r and r[0])       # one column = a list
    if len(data) == 1 and head[0].strip("：:").lower() not in _FIELD_HEADER and len(head) == len(data[0]):
        pairs = [f"{k}：{v}" for k, v in zip(head, data[0]) if k and v]
        return "，".join(pairs)
    return "，".join(f"{r[0]}：{' '.join(c for c in r[1:] if c)}" for r in data if r and r[0])


def normalize(text: str) -> str:
    """Rewrite tables into lines; blank out thematic breaks. Everything else (headings,
    lists, quotes) the segmenter already handles line by line, so it passes through."""
    src = str(text or "")
    if "|" not in src and not any(c.lstrip().startswith(("---", "***", "___", "~~~"))
                                  for c in src.splitlines()):
        return src                       # nothing block-structural to lose: no parse, no risk
    lines = src.split("\n")
    out = list(lines)
    tokens = _MD.parse(src, {})
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        span = tok.map
        if span and tok.type == "hr":
            for ln in range(span[0], span[1]):
                out[ln] = ""
        elif span and tok.type == "table_open":
            rows, close = _table_rows(tokens, i)
            line = _table_line(rows)
            for ln in range(span[0], span[1]):
                out[ln] = ""
            out[span[0]] = line
            i = close
        i += 1
    return "\n".join(out)
