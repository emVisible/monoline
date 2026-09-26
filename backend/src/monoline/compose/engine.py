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

    def headline_px(text: str, *, base: int, min_px: int, ref_chars: int, max_lines: int = 1) -> int:
        """Deterministic fit: shrink a headline as it exceeds ref_chars, floor at min_px.

        `max_lines` is the real lever. Fitting to one line made a 24-char statement drop
        to 67px — body-text size on a slide meant to carry a single thought. Allowing two
        lines keeps it at display size and lets the frame's vertical space do the work."""
        n = max(1, len((text or "").strip()))
        per_line = -(-n // max(1, max_lines))          # ceil: chars per line when wrapped
        px = int(base * ref_chars / max(per_line, 1))
        return max(min_px, min(base, px))

    env.globals["headline_px"] = headline_px

    def count_up(text: str):
        """Split a value into prefix + a clean numeric core + suffix for a
        deterministic count-up. Returns None unless the whole string is exactly
        [non-digit prefix][one number][non-digit suffix] — so thousands
        separators ("1,000") or multi-number text fall back to static rendering."""
        import re
        m = re.match(r"^([^\d-]*)(-?\d+(?:\.\d+)?)([^\d]*)$", (text or "").strip())
        if not m:
            return None
        prefix, num, suffix = m.group(1), m.group(2), m.group(3)
        dec = len(num.split(".")[1]) if "." in num else 0
        return {"prefix": prefix, "num": num, "dec": dec, "suffix": suffix}

    env.globals["count_up"] = count_up
    from ..pipeline.display_text import kinetic_chunks as _kinetic
    from .icons import svg as _icon_svg
    from .viz import (argmax as _argmax, delta as _delta, donut as _donut, funnel_widths as _funnel_w,
                      highlight as _highlight, max_drop as _max_drop, pct as _pct, peak_marker as _peak,
                      polar as _polar, ring as _ring, row_bars as _row_bars, sparkline as _spark,
                      stack_widths as _stack_w)
    env.globals["icon_svg"] = _icon_svg
    env.globals["pct"] = _pct
    env.globals["ring"] = _ring
    env.globals["row_bars"] = _row_bars
    env.globals["polar"] = _polar
    env.globals["funnel_widths"] = _funnel_w
    env.globals["stack_widths"] = _stack_w
    env.globals["sparkline"] = _spark
    env.globals["peak_marker"] = _peak
    env.globals["argmax"] = _argmax
    env.globals["highlight"] = _highlight
    env.globals["max_drop"] = _max_drop
    env.globals["donut"] = _donut
    env.globals["delta"] = _delta
    env.globals["kinetic_chunks"] = _kinetic
    return env


def render_composition(timings: Timings, plan: ScenePlan, *, title: str = "", vo_src: str = "audio/narration.wav",
                       layout: str = "minimal") -> str:
    env = _env()
    tmpl = env.get_template("base.html.j2")
    w, h = plan.canvas.width, plan.canvas.height
    aspect = "portrait" if h > w * 1.1 else ("square" if abs(h - w) <= w * 0.1 else "landscape")
    html = tmpl.render(
        canvas=plan.canvas,
        aspect=aspect,
        layout=layout if layout in ("minimal", "editorial", "bold") else "minimal",
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
