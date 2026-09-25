"""User-level brand identity (V30) — label, theme, accent, logo.

Deliberately NOT on the job row: this is who you are, not what one video says. It is
edited once, on the intake screen, and copied into a job's config when the job is
created. The Studio's appearance card then adjusts THAT job only — which is the
difference between "set up before generating" and "tune after generating".

The logo is frozen to a content-hashed filename so a re-upload can never leave a
composition pointing at stale bytes.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from .settings import Settings

_LABELS = {"label": "Monoline", "theme": "mono-ink", "accent": ""}
_ALLOWED_IMG = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MAX_IMG = 12 * 1024 * 1024


def _file(settings: Settings) -> Path:
    return settings.app_dir / "brand.json"


def _dir(settings: Settings) -> Path:
    d = settings.app_dir / "brand"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load(settings: Settings) -> dict:
    """The saved identity, merged over the built-in defaults."""
    out = dict(_LABELS)
    try:
        import json
        data = json.loads(_file(settings).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            out.update({k: str(v) for k, v in data.items() if k in _LABELS})
    except (OSError, ValueError):
        pass
    logo = _logo_path(settings)
    out["logo"] = logo.name if logo else ""
    return out


def _logo_path(settings: Settings) -> Path | None:
    """The stored logo, or None. Never Path("") — that IS the cwd and .exists() on it
    is True, which turned a first upload into `unlink('.')`."""
    hits = sorted(_dir(settings).glob("logo-*"))
    return hits[-1] if hits else None


def save(settings: Settings, *, label: str | None = None, theme: str | None = None,
         accent: str | None = None) -> dict:
    import json
    cur = load(settings)
    if label is not None:
        cur["label"] = label.strip() or "Monoline"
    if theme is not None:
        cur["theme"] = theme
    if accent is not None:
        cur["accent"] = accent.strip()
    keep = {k: cur[k] for k in _LABELS}
    _file(settings).write_text(json.dumps(keep, ensure_ascii=False, indent=2), encoding="utf-8")
    return cur


def put_logo(settings: Settings, data: bytes, suffix: str) -> dict:
    if len(data) > _MAX_IMG:
        raise ValueError(f"image too large ({len(data)} > {_MAX_IMG})")
    if suffix.lower() not in _ALLOWED_IMG:
        raise ValueError(f"unsupported image type {suffix!r}")
    old = _logo_path(settings)
    dest = _dir(settings) / f"logo-{hashlib.sha1(data).hexdigest()[:12]}{suffix.lower()}"
    dest.write_bytes(data)
    if old and old != dest:
        old.unlink(missing_ok=True)
    return load(settings)


def drop_logo(settings: Settings) -> dict:
    old = _logo_path(settings)
    if old:
        old.unlink(missing_ok=True)
    return load(settings)


def logo_file(settings: Settings, name: str) -> Path | None:
    """The stored logo for `name`, or None if it isn't there (name comes from the URL)."""
    if not name:
        return None
    p = (_dir(settings) / Path(name).name)
    return p if p.exists() else None


def apply_to_config(settings: Settings, config: dict) -> dict:
    """Fill a new job's appearance config from the identity, without clobbering
    whatever the intake screen explicitly chose."""
    b = load(settings)
    config.setdefault("brand", b["label"])
    config.setdefault("theme", b["theme"])
    config.setdefault("accent", b["accent"])
    if b["logo"]:
        config.setdefault("logo", b["logo"])
    return config


def freeze_logo_into(settings: Settings, job_id: str, logo_name: str) -> str:
    """Copy the user-level logo into the job's composition assets; return the relative
    path the template reads. Empty when there is nothing to freeze."""
    from .pipeline.workspace import Workspace

    src = _dir(settings) / Path(logo_name).name
    if not logo_name or not src.is_file():
        return ""
    ws = Workspace(settings.workspaces_dir / job_id).ensure()
    rel = f"assets/{logo_name}"
    dst = ws.composition / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy2(src, dst)
    return rel
