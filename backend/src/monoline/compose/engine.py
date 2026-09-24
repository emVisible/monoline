"""Compose engine — render sceneplan + timings → HyperFrames index.html.

Replaces generate.py. Autoescape ON (all display text is escaped), then a
fail-closed determinism assertion.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..ir.sceneplan import ScenePlan
from ..ir.timings import Timings
from .assert_determinism import assert_determinism

_TEMPLATES = Path(__file__).parent / "templates"


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html", "xml", "j2"], default_for_string=True),
        trim_blocks=False,
        lstrip_blocks=False,
    )

    def headline_px(text: str, *, base: int, min_px: int, ref_chars: int) -> int:
        """Deterministic fit: shrink a headline as it exceeds ref_chars, floor at min_px."""
        n = max(1, len((text or "").strip()))
        if n <= ref_chars:
            return base
        px = int(base * ref_chars / n)
        return max(min_px, px)

    env.globals["headline_px"] = headline_px
    from .icons import svg as _icon_svg
    from .viz import pct as _pct, ring as _ring, row_bars as _row_bars
    env.globals["icon_svg"] = _icon_svg
    env.globals["pct"] = _pct
    env.globals["ring"] = _ring
    env.globals["row_bars"] = _row_bars
    return env


def render_composition(timings: Timings, plan: ScenePlan, *, title: str = "", vo_src: str = "audio/narration.wav") -> str:
    env = _env()
    tmpl = env.get_template("base.html.j2")
    w, h = plan.canvas.width, plan.canvas.height
    aspect = "portrait" if h > w * 1.1 else ("square" if abs(h - w) <= w * 0.1 else "landscape")
    html = tmpl.render(
        canvas=plan.canvas,
        aspect=aspect,
        total=timings.total,
        segments=timings.segments,
        scenes=plan.scenes,
        theme=plan.theme,
        brand=plan.brand,
        captions=plan.captions,
        vo_src=vo_src,
        title=title or (plan.scenes[0].slots.get("headline") if plan.scenes else "") or "Monoline",
    )
    assert_determinism(html)
    return html
