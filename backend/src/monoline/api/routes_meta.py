"""Meta API (V2) — theme registry + saved presets (config recipes).

V8 adds the voice registry and per-voice audition samples (synthesized once,
then cached under cache/voices/ so repeat previews are instant).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/themes")
async def list_themes(request: Request) -> dict:
    from ..settings import get_settings
    from ..themes import available
    return {"themes": available(get_settings())}


@router.get("/icons")
async def list_icons() -> dict:
    from ..compose.icons import names
    return {"icons": names()}


@router.get("/voices")
async def list_voices() -> dict:
    from ..voices import DEFAULT_VOICE, available
    return {"voices": available(), "default": DEFAULT_VOICE}


@router.get("/voices/{vid}/sample")
async def voice_sample(vid: str, request: Request):
    """Audition a voice: synthesize its sample line once, cache the wav, serve it."""
    import os

    from ..hf.cli import HF
    from ..settings import get_settings
    from ..voices import is_known_voice, sample_text, voice_lang

    if not is_known_voice(vid):
        raise HTTPException(422, f"unknown voice {vid!r}")
    s = get_settings()
    cache = s.cache_dir / "voices"
    cache.mkdir(parents=True, exist_ok=True)
    # r2 = synthesized with a tone-carrying G2P. The revision is in the filename so an
    # r1 audition wav (recorded before Mandarin tones reached the model) can never be
    # served from cache after the fix.
    wav = cache / f"{vid}.r2.wav"
    if not wav.exists():
        textf = cache / f"{vid}.sample.txt"
        textf.write_text(sample_text(vid), encoding="utf-8")
        tmp = wav.with_name(f"{vid}.tmp.wav")  # soundfile infers format from the extension → must end .wav
        try:
            await HF(s).tts(str(textf), str(tmp), voice=vid, lang=voice_lang(vid))
            os.replace(tmp, wav)
        except Exception as e:  # noqa: BLE001 — surface synth errors, never leave a partial cache
            tmp.unlink(missing_ok=True)
            raise HTTPException(502, f"voice preview failed: {e}") from e
        finally:
            textf.unlink(missing_ok=True)
    return FileResponse(str(wav), media_type="audio/wav")


class PresetIn(BaseModel):
    name: str = Field(min_length=1)
    config: dict


@router.get("/presets")
async def list_presets(request: Request) -> dict:
    m = request.app.state.manager
    return {"presets": await m.repo.list_presets()}


@router.post("/presets")
async def create_preset(body: PresetIn, request: Request) -> dict:
    m = request.app.state.manager
    pid = await m.repo.save_preset(body.name.strip(), body.config)
    return {"id": pid}


@router.delete("/presets/{pid}")
async def delete_preset(pid: str, request: Request) -> dict:
    m = request.app.state.manager
    await m.repo.delete_preset(pid)
    return {"removed": True}


# --- V30 brand identity: set up once, on the intake screen, applied to every new job ---

class BrandPatch(BaseModel):
    label: str | None = None
    theme: str | None = None
    accent: str | None = None


def _brand_view(s) -> dict:
    from .. import brand
    b = brand.load(s)
    return {"label": b["label"], "theme": b["theme"], "accent": b["accent"],
            "logo": b["logo"], "logo_url": f"/api/brand/logo?name={b['logo']}" if b["logo"] else ""}


@router.get("/brand")
async def get_brand() -> dict:
    from ..settings import get_settings
    return _brand_view(get_settings())


@router.patch("/brand")
async def patch_brand(body: BrandPatch) -> dict:
    from .. import brand
    from ..settings import get_settings
    from ..themes import available
    s = get_settings()
    if body.theme is not None and body.theme not in {t["id"] for t in available(s)}:
        raise HTTPException(422, f"unknown theme {body.theme!r}")
    if body.accent is not None and body.accent.strip() and not re.fullmatch(r"#[0-9a-fA-F]{6}", body.accent.strip()):
        raise HTTPException(422, "accent must be a #rrggbb hex color")
    brand.save(s, label=body.label, theme=body.theme, accent=body.accent)
    return _brand_view(s)


@router.get("/brand/logo")
async def get_brand_logo(name: str = ""):
    from .. import brand
    from ..settings import get_settings
    p = brand.logo_file(get_settings(), name)
    if p is None:
        raise HTTPException(404, "no such logo")
    return FileResponse(str(p), headers={"cache-control": "no-store"})


@router.post("/brand/logo")
async def put_brand_logo(file: UploadFile = File(...)) -> dict:
    from pathlib import Path

    from .. import brand
    from ..settings import get_settings
    s = get_settings()
    data = await file.read()
    try:
        brand.put_logo(s, data, Path(file.filename or "").suffix)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return _brand_view(s)


@router.delete("/brand/logo")
async def del_brand_logo() -> dict:
    from .. import brand
    from ..settings import get_settings
    return _brand_view(brand.drop_logo(get_settings()))
