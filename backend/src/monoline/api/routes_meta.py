"""Meta API (V2) — theme registry + saved presets (config recipes).

V8 adds the voice registry and per-voice audition samples (synthesized once,
then cached under cache/voices/ so repeat previews are instant).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
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
