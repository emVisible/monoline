"""Inline SVG icon library (V3) — line icons, stroke=currentColor, no files/network.

Deterministic static markup only (safe for HyperFrames render). Names are the
whitelist; unknown names render nothing (no injection). Color comes from the
surrounding CSS `color` (themes set it to the accent).
"""
from __future__ import annotations

_ICONS: dict[str, str] = {
    "chart": '<line x1="5" y1="20" x2="5" y2="12"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="19" y1="20" x2="19" y2="9"/><line x1="3" y1="20" x2="21" y2="20"/>',
    "bolt": '<path d="M13 2 4 14h6l-1 8 9-12h-6z"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.8" fill="currentColor" stroke="none"/>',
    "bulb": '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10c1 1 1.5 2 1.5 3h5c0-1 .5-2 1.5-3a6 6 0 0 0-4-10z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><circle cx="12" cy="8" r="0.8" fill="currentColor" stroke="none"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "layers": '<path d="M12 3 3 8l9 5 9-5z"/><path d="M3 13l9 5 9-5"/>',
    "cpu": '<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M10 3v3M14 3v3M10 18v3M14 18v3M3 10h3M3 14h3M18 10h3M18 14h3"/>',
    "sparkles": '<path d="M11 4l1.4 3.6L16 9l-3.6 1.4L11 14l-1.4-3.6L6 9l3.6-1.4z"/><path d="M18 14l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/>',
    "eye": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "wave": '<path d="M2 12c2-3.5 4-3.5 6 0s4 3.5 6 0 4-3.5 6 0"/>',
    "grid": '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
    "quote": '<path d="M9 7H5v5h4v-1c0 2-1 3-3 4M19 7h-4v5h4v-1c0 2-1 3-3 4"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1" fill="currentColor" stroke="none"/><circle cx="4.5" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="4.5" cy="18" r="1" fill="currentColor" stroke="none"/>',
    "scale": '<path d="M12 4v16M7 20h10M5 8h14M5 8l-2.5 6h5zM19 8l-2.5 6h5z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "flag": '<path d="M6 21V4M6 4h11l-2 4 2 4H6"/>',
}

# default icon per scene kind (planner auto-assigns; user can override/clear)
KIND_ICON = {
    "title": "sparkles", "statement": "", "section": "arrow", "stat": "chart",
    "table": "grid", "cards": "layers", "compare": "scale", "quote": "quote",
    "list": "list", "note": "", "definition": "bulb", "summary": "check",
}


def names() -> list[str]:
    return sorted(_ICONS.keys())


def svg(name: str, *, size: int | None = None) -> str:
    inner = _ICONS.get(name)
    if not inner:
        return ""
    dim = f' width="{size}" height="{size}"' if size else ""
    return (f'<svg{dim} viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{inner}</svg>')
