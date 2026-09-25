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
