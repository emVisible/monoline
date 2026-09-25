"""Rebuild compose/data/icons.json from the vendored Lucide sprite.

Why vendor: compositions must be deterministic and offline (assert_determinism blocks any
remote resource), so icon path data is inlined at compose time from a local file. Lucide is
ISC-licensed; attribution lives in vendor/lucide/LICENSE-ISC.txt.

Usage:  python scripts/build_icons.py            # regenerate
        python scripts/build_icons.py --check    # fail if data/icons.json is stale
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPRITE = ROOT / "vendor/lucide/sprite.svg"
OUT = ROOT / "src/monoline/compose/data/icons.json"

# Our stable key → Lucide icon name. Keys are what plans and the Studio store, so renaming a
# Lucide icon upstream never breaks a saved scene.
MANIFEST: dict[str, str] = {
    # data & measurement
    "chart": "chart-column", "bars": "chart-bar", "trend_up": "chart-line", "trend_down": "chart-bar-decreasing",
    "area": "chart-area", "pie": "chart-pie", "gauge": "gauge", "percent": "percent", "calc": "calculator",
    "activity": "activity", "candlestick": "chart-candlestick", "gantt": "chart-gantt",
    # compute & product
    "cpu": "cpu", "circuit": "circuit-board", "code": "code", "terminal": "terminal", "binary": "binary",
    "brackets": "brackets", "database": "database", "server": "server", "cloud": "cloud", "wifi": "wifi",
    "signal": "signal", "satellite": "satellite", "bot": "bot", "brain": "brain", "brain_circuit": "brain-circuit",
    "atom": "atom", "lock": "lock", "shield": "shield-check", "key": "key", "settings": "settings",
    "sliders": "sliders-horizontal", "wrench": "wrench", "hammer": "hammer", "puzzle": "puzzle", "workflow": "workflow",
    # structure & process
    "layers": "layers", "stack": "square-stack", "box": "box", "package": "package", "network": "network",
    "branch": "git-branch", "commit": "git-commit-horizontal", "share": "share-2", "link": "link-2",
    "split": "split", "funnel": "funnel", "grid2": "grid-2x2", "grid3": "grid-3x3", "dashboard": "layout-dashboard",
    "panels": "panels-top-left", "table": "table", "list": "list", "list_check": "list-checks",
    "list_ordered": "list-ordered", "todo": "list-todo", "filter": "list-filter", "clipboard": "clipboard-list",
    "folder": "folder", "file": "file-text", "bookmark": "bookmark",
    # people, places, goods
    "users": "users", "user": "user-round", "building": "building", "complex": "building-complex",
    "store": "store", "factory": "factory", "warehouse": "warehouse", "truck": "truck",
    "wallet": "wallet", "coins": "coins", "banknote": "banknote", "card": "credit-card", "piggy": "piggy-bank",
    "receipt": "receipt", "cart": "shopping-cart", "bag": "shopping-bag", "scale": "scale",
    # time & milestones
    "clock": "clock", "calendar": "calendar-days", "range": "calendar-range", "hourglass": "hourglass",
    "timer": "timer", "watch": "watch", "milestone": "milestone", "flag": "flag", "route": "route",
    "footprints": "footprints", "pin": "pin", "map_pin": "map-pin", "compass": "compass",
    "refresh": "refresh-cw", "repeat": "repeat", "loader": "loader", "play": "play",
    # nature & world
    "sun": "sun", "moon": "moon", "flame": "flame", "droplet": "droplet", "wind": "wind", "snow": "snowflake",
    "globe": "globe", "earth": "earth",
    # mind, insight, science
    "bulb": "lightbulb", "sparkles": "sparkles", "target": "target", "crosshair": "crosshair", "eye": "eye",
    "scan": "scan-eye", "search": "search", "telescope": "telescope", "microscope": "microscope",
    "flask": "flask-conical", "wave": "waves-horizontal", "audio": "audio-waveform",
    # communication
    "message": "message-square", "quote": "quote", "mail": "mail", "send": "send", "inbox": "inbox",
    "bell": "bell", "mic": "mic", "phone": "phone", "volume": "volume-2",
    # status & value
    "check": "circle-check", "alert": "triangle-alert", "info": "info", "award": "award", "trophy": "trophy",
    "medal": "medal", "star": "star", "heart": "heart", "handshake": "handshake", "hand_heart": "hand-heart",
    "bolt": "zap", "rocket": "rocket", "arrow": "arrow-right", "arrow_up": "arrow-up-right",
    "arrow_down": "arrow-down-right", "chevron": "chevron-right", "chevrons": "chevrons-right",
    "title": "type", "heading": "heading", "list_bullet": "list-start", "grid": "layout-grid",
    # primitives for badges, deltas and UI marks
    "cross": "x", "plus": "plus", "minus": "minus", "dot": "circle-dot", "circle": "circle",
    "square": "square", "menu": "menu", "ellipsis": "ellipsis", "pause": "pause",
    "upload": "upload", "download": "download", "print": "printer",
}


def symbols() -> dict[str, str]:
    raw = SPRITE.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r'<symbol id="([^"]+)"[^>]*>(.*?)</symbol>', raw, re.S):
        body = re.sub(r"\s+", " ", m.group(2)).strip()
        out[m.group(1)] = body
    return out


def main() -> int:
    syms = symbols()
    data, missing = {}, []
    for key, lucide_name in MANIFEST.items():
        body = syms.get(lucide_name)
        if not body:
            missing.append(f"{key}→{lucide_name}")
            continue
        data[key] = body
    if missing:
        print(f"WARNING: {len(missing)} not in sprite: {', '.join(missing)}")
    dupes: dict[str, list[str]] = {}
    for key, body in data.items():
        dupes.setdefault(body, []).append(key)
    clashes = [ks for ks in dupes.values() if len(ks) > 1]
    if clashes:
        print("ERROR: identical geometry under different keys: " + "; ".join("=".join(ks) for ks in clashes))
        return 1
    payload = json.dumps({"_source": f"lucide-static v1.48.0 (ISC) — see vendor/lucide", "icons": data},
                         ensure_ascii=False, indent=0, sort_keys=True)
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current.strip() != payload.strip():
            print("icons.json is stale — run: python scripts/build_icons.py")
            return 1
        print("icons.json is up to date")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(payload, encoding="utf-8")
    print(f"wrote {OUT} · {len(data)} icons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
