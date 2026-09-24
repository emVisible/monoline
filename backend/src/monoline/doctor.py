"""Environment truth probes. `monoline doctor` and GET /api/health both use this.

Gate on the `ok` field, never on process exit code (hyperframes doctor always
exits 0; we fold its JSON into our own verdict).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import httpx

from .settings import Settings, get_settings


def _run(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _node_ok(settings: Settings) -> dict:
    node = settings.resolve_node()
    if not node:
        return {"name": "node", "state": "missing", "found": None,
                "expected": ">=22 <23", "fix": "nvm install 22  (or set MONOLINE_NODE_BIN)"}
    try:
        v = _run([node, "--version"]).stdout.strip()
        major = int(re.sub(r"[^0-9]", "", v.lstrip("v"))[:2])
        ok = major == 22
        return {"name": "node", "state": "ok" if ok else "wrong_version",
                "found": f"{v} @ {node}", "expected": ">=22 <23",
                "fix": None if ok else "point MONOLINE_NODE_BIN at a node 22"}
    except Exception as e:  # noqa: BLE001
        return {"name": "node", "state": "error", "found": str(e), "expected": ">=22 <23", "fix": None}


def _ffmpeg_ok() -> dict:
    ff = shutil.which("ffmpeg")
    fp = shutil.which("ffprobe")
    ok = bool(ff and fp)
    return {"name": "ffmpeg", "state": "ok" if ok else "missing",
            "found": ff, "expected": "ffmpeg + ffprobe on PATH",
            "fix": None if ok else "brew install ffmpeg"}


def _hf_doctor(settings: Settings) -> dict:
    """Probe `hyperframes doctor --json`. Prefer the installed sidecar binary (no
    npx network resolution); fall back to npx. Short timeout — this runs on the
    health path, so it must degrade fast rather than hang."""
    local = settings.sidecar_dir / "node_modules" / ".bin" / "hyperframes"
    cmd = [str(local), "doctor", "--json"] if local.exists() else ["npx", "--yes", f"hyperframes@{settings.hf_version}", "doctor", "--json"]
    try:
        out = _run(cmd, timeout=12).stdout
        m = re.search(r"\{.*\}", out, re.S)
        data = json.loads(m.group(0)) if m else {}
        # HF's own `ok` is all-or-nothing and trips on OPTIONAL pieces we don't use
        # (its bundled Kokoro/MusicGen, Docker). Judge only what our pipeline needs.
        by_name = {c.get("name"): c.get("ok") for c in data.get("checks", [])}
        critical = ["Version", "Chrome", "FFmpeg", "FFprobe"]
        missing = [n for n in critical if not by_name.get(n)]
        ok = (not missing) if by_name else bool(data.get("ok"))
        return {"name": "hyperframes", "state": "ok" if ok else "warn",
                "found": f"v{settings.hf_version}" + (f" · missing {missing}" if missing else ""),
                "expected": "Version + Chrome + FFmpeg/FFprobe ready", "detail": data}
    except Exception as e:  # noqa: BLE001
        return {"name": "hyperframes", "state": "error", "found": str(e)[:120],
                "expected": "doctor.ok == true", "fix": "run: cd sidecar && npx hyperframes doctor"}


def _chrome_ok(settings: Settings) -> dict:
    # HyperFrames manages its own pinned headless shell under ~/.cache/hyperframes/chrome
    # (not our app cache). Check the real location(s) so a working render isn't reported
    # as "will_download".
    candidates = [
        Path.home() / ".cache" / "hyperframes" / "chrome",
        Path.home() / "Library" / "Caches" / "hyperframes" / "chrome",
        settings.cache_dir / "browser",
    ]
    for base in candidates:
        if base.exists() and any(base.rglob("chrome-headless-shell*")):
            return {"name": "chrome", "state": "ok", "found": str(base),
                    "expected": "HF-managed pinned headless shell (auto-downloads once)", "fix": None}
    return {"name": "chrome", "state": "will_download", "found": None,
            "expected": "HF-managed pinned headless shell (auto-downloads once on first render)",
            "fix": "auto — HyperFrames fetches it on first render; or `npx hyperframes browser ensure`"}


def _fonts_ok(settings: Settings) -> dict:
    fdir = settings.vendor_dir / "fonts"
    otf = list(fdir.glob("*.otf")) + list(fdir.glob("*.ttf"))
    lic = (fdir / "OFL.txt").exists() or (fdir / "LICENSE-OFL.txt").exists()
    ok = bool(otf) and lic
    return {"name": "ofl_cjk_font", "state": "ok" if ok else "missing",
            "found": [p.name for p in otf], "expected": "an OFL CJK .otf/.ttf + OFL.txt in backend/vendor/fonts",
            "fix": "make fonts  (downloads Noto Sans SC / LXGWWenKai OFL)"}


def _gsap_ok(settings: Settings) -> dict:
    g = settings.vendor_dir / "gsap.min.js"
    return {"name": "gsap_vendored", "state": "ok" if g.exists() else "missing",
            "found": str(g) if g.exists() else None, "expected": "backend/vendor/gsap.min.js",
            "fix": "vendor GSAP (no CDN in compositions)"}


def _sidecar_ok(settings: Settings) -> dict:
    try:
        r = httpx.get(f"{settings.sidecar_url}/health", timeout=2)
        ok = r.status_code == 200
        return {"name": "render_sidecar", "state": "ok" if ok else "down",
                "found": f"{settings.sidecar_url} → {r.status_code}",
                "expected": "running (spawned by `monoline start`)", "fix": "make start"}
    except Exception:  # noqa: BLE001
        return {"name": "render_sidecar", "state": "down", "found": settings.sidecar_url,
                "expected": "running", "fix": "spawned automatically by `monoline start`"}


def run_doctor(settings: Settings | None = None, *, probe_sidecar: bool = True) -> dict:
    settings = settings or get_settings()
    checks = [
        _node_ok(settings),
        _ffmpeg_ok(),
        _gsap_ok(settings),
        _fonts_ok(settings),
        _chrome_ok(settings),
        _hf_doctor(settings),
    ]
    if probe_sidecar:
        checks.append(_sidecar_ok(settings))
    # hard blockers for rendering: node22, ffmpeg, gsap, font. hf/chrome/sidecar are soft at M0.
    hard = {"node", "ffmpeg", "gsap_vendored", "ofl_cjk_font"}
    ok = all(c["state"] == "ok" for c in checks if c["name"] in hard)
    return {"ok": ok, "checks": checks, "app_dir": str(settings.app_dir), "port": settings.port}
