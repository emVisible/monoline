"""Deterministic SVG data-viz (V3b) — progress ring + bar from slot values.

Pure static markup computed from numbers at compose time (no runtime, no network,
no randomness → safe for HyperFrames). Colors come from CSS classes (theme vars).
"""
from __future__ import annotations

import re

_C = 263.894  # circumference of r=42 in a 0..100 viewBox (2*pi*42)


def pct(value: object) -> float | None:
    """Return a 0–100 percentage if the value clearly encodes one, else None.
    Accepts "68.8%", "42 %". A bare fraction "0.42" counts only when it's a
    visually meaningful proportion (≥0.05 → 5%); smaller decimals like a learning
    rate "0.001" are magnitudes, not shares, so they render as a plain number
    rather than a near-empty ring."""
    if value is None:
        return None
    s = str(value).strip()
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", s)
    if m:
        return max(0.0, min(100.0, float(m.group(1))))
    m = re.fullmatch(r"0?\.[0-9]+", s)  # bare 0.x fraction
    if m:
        p = float(s) * 100
        return max(0.0, min(100.0, p)) if p >= 5.0 else None
    return None


def ring(p: float, *, track: str = "ring-track", fill: str = "ring-fill") -> str:
    offset = round(_C * (1 - p / 100.0), 2)
    return (
        '<svg class="ring" viewBox="0 0 100 100" aria-hidden="true">'
        f'<circle class="{track}" cx="50" cy="50" r="42" fill="none" stroke-width="7"/>'
        f'<circle class="{fill}" cx="50" cy="50" r="42" fill="none" stroke-width="7" stroke-linecap="round" '
        f'stroke-dasharray="{_C}" stroke-dashoffset="{offset}" transform="rotate(-90 50 50)"/>'
        "</svg>"
    )


_NUM_ONLY = re.compile(r"-?\d+(?:\.\d+)?")


def row_bars(values: list) -> list[float | None]:
    """Bar width (0–100) per table row, or None when a bar would be misleading.

    - all values are percentages → use them directly (68.8% → 68.8).
    - all values are bare numbers (≥2 rows) → normalize to the max (relative bars),
      so "速度 120 / 功耗 45 / 成本 30" reads as a comparison.
    - anything mixed / non-numeric → no bars (don't invent a scale).
    """
    vals = [str(v).strip() for v in values]
    if not vals:
        return []
    pcts = [pct(v) for v in vals]
    if all(p is not None for p in pcts):
        return pcts  # type: ignore[return-value]
    if len(vals) >= 2:
        try:
            nums = [float(v) if _NUM_ONLY.fullmatch(v) else None for v in vals]
        except ValueError:
            nums = [None] * len(vals)
        if all(n is not None for n in nums):
            mx = max(nums)  # type: ignore[type-var]
            if mx and mx > 0:
                return [round(float(n) / mx * 100.0, 1) for n in nums]  # type: ignore[arg-type]
    return [None] * len(vals)


def polar(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    """A point on a circle, in 0-100 view units. Jinja has no trig and the renderer must
    never measure the DOM, so ring/cycle geometry is computed here."""
    import math

    a = math.radians(deg)
    return round(cx + r * math.cos(a), 2), round(cy + r * math.sin(a), 2)


def funnel_widths(values: list) -> list[float]:
    """Bar widths (0-100) for a funnel: normalized to the largest value, floored so the
    last stage is still readable, and monotonically non-increasing so it looks like a
    funnel even when the numbers do not perfectly shrink."""
    nums: list[float] = []
    for v in values:
        p = pct(v)
        if p is not None:
            nums.append(p)
            continue
        m = _NUM_ONLY.search(str(v))
        nums.append(float(m.group(0)) if m else 0.0)
    if not nums:
        return []
    mx = max(nums) or 1.0
    out = [max(26.0, round(n / mx * 100.0, 1)) for n in nums]
    for i in range(1, len(out)):
        out[i] = min(out[i], out[i - 1])
    return out


def stack_widths(n: int) -> list[float]:
    """Layer widths for a stack diagram: widest at the bottom (the foundation), so the
    pile reads as architecture rather than as a list."""
    if n <= 1:
        return [86.0]
    return [round(60.0 + i * (38.0 / (n - 1)), 1) for i in range(n)]


def _nums(values: list) -> list[float]:
    """First number in each value, as a float ('Q3 1.2M' → 1.2). Non-numerics → 0.0."""
    out = []
    for v in values:
        m = _NUM_ONLY.search(str(v))
        out.append(float(m.group(0)) if m else 0.0)
    return out


def _series(values: object) -> list[float]:
    """Numbers in order, from whatever a slot holds. A list comes through as-is; a
    string is split on separators first, because 「1.2 / 1.9 / 2.4」 as one string
    would otherwise be read digit by digit into a jagged lie."""
    if isinstance(values, str):
        values = re.split(r"[/,;、|→\s]+", values.strip())
    return [float(m.group(0)) for m in (_NUM_ONLY.search(str(v)) for v in (values or [])) if m]


def _points(nums: list[float], w: int, h: int, pad: float = 10.0) -> list[tuple[float, float]]:
    """Series coordinates in the chart's own viewBox, scaled to its own min/max.

    Shared by the line and its annotation so a callout can never drift off the point
    it is pointing at. Rounded to 2dp — identical input always yields identical markup."""
    lo, hi = min(nums), max(nums)
    span = hi - lo
    n = len(nums)
    return [(round(i / (n - 1) * (w - pad * 2) + pad, 2),
             round(h / 2, 2) if span == 0 else round(h - pad - (v - lo) / span * (h - pad * 2), 2))
            for i, v in enumerate(nums)]


def sparkline(values: list, *, w: int = 320, h: int = 96) -> str:
    """A trend line for a short numeric series, scaled to its own min/max.

    Returns '' unless at least two entries actually carry a number — a line through
    one point is a lie, and a flat line through 「营收」「利润」 would be worse."""
    nums = _series(values)
    if len(nums) < 2:
        return ""
    pts = [f"{x},{y}" for x, y in _points(nums, w, h)]
    lx, ly = pts[-1].split(",")
    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" aria-hidden="true">'
        f'<polyline class="sl-line" points="{" ".join(pts)}" fill="none" stroke-width="3" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle class="sl-dot" cx="{lx}" cy="{ly}" r="5"/></svg>'
    )


def peak_marker(values: list, *, w: int = 320, h: int = 96) -> dict | None:
    """The series' high point as {x, y, value, index} — the annotation a designed slide
    makes and a generated one omits.

    None when fewer than three numbers exist (two points are a comparison, not a shape
    to read a peak off) and when the peak IS the last point: the hero figure already
    shows that value, so a callout would only repeat it. Ties resolve to the earliest
    index, which keeps the markup deterministic."""
    nums = _series(values)
    if len(nums) < 3:
        return None
    i = max(range(len(nums)), key=lambda k: (nums[k], -k))
    if i == len(nums) - 1:
        return None
    x, y = _points(nums, w, h)[i]
    return {"x": x, "y": y, "value": str(values[i]).strip(), "index": i}


def donut(shares: list) -> str:
    """A segmented ring for part-of-whole data (4 tones max, to stay monochrome).

    Segments are normalized, so '45 / 30 / 25' and '45% / 30% / 25%' both work. Each
    arc is one dash on the same circle, offset by the running total — no paths, no
    trig, nothing to desync at render time."""
    nums = [n for n in _series(shares) if n > 0][:4]
    if len(nums) < 2:
        return ""
    total = sum(nums)
    segs, acc = [], 0.0
    for i, v in enumerate(nums):
        frac = v / total
        dash = round(frac * _C, 2)
        segs.append(
            f'<circle class="dn-{i + 1}" cx="50" cy="50" r="42" fill="none" stroke-width="13" '
            f'stroke-dasharray="{dash} {round(_C - dash, 2)}" stroke-dashoffset="{round(-acc * _C, 2)}" '
            'transform="rotate(-90 50 50)"/>'
        )
        acc += frac
    return ('<svg class="donut" viewBox="0 0 100 100" aria-hidden="true">'
            f'<circle class="dn-track" cx="50" cy="50" r="42" fill="none" stroke-width="13"/>'
            f'{"".join(segs)}</svg>')


_DELTA_SIGN = re.compile(r"^\s*([+\-−])\s*(\d)")
# the number plus whatever unit glyph hugs it: 30% / 3.4 pp / 12 个点 / 2 倍 / 1.5 亿
_DELTA_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(%|％|pp|个百分点|个点|倍|万|亿|k|K|M|B)?")
_UP_WORDS = ("增长", "上涨", "提升", "提高", "增加", "上升", "翻倍", "环比增", "同比增", "grew", "growth", "up ")
_DOWN_WORDS = ("下降", "下滑", "减少", "降低", "回落", "下跌", "缩水", "decline", "fell", "down ")


def delta(text: object) -> dict | None:
    """Classify a change statement into {dir, sign, num, suffix} for an arrow chip.

    Reads a leading +3 / -12% first, then Chinese/English growth words. Returns None
    when the text carries no direction — the caller then renders the plain number,
    which is honest; an invented arrow is not."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    m = _DELTA_SIGN.match(s)
    neg = None
    if m:
        neg = m.group(1) in "-−"
    else:
        low = s.lower()
        up = any(k in low for k in _UP_WORDS)
        down = any(k in low for k in _DOWN_WORDS)
        if up == down:
            return None
        neg = down
    n = _DELTA_NUM.search(s)
    if not n:
        return None
    return {"dir": "down" if neg else "up", "sign": "−" if neg else "+",
            "num": n.group(1), "suffix": (n.group(2) or "").strip()}
