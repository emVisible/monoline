"""Script-writing API (V1) — turn a topic into narration text via the LLM layer."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..llm.client import LLMError, LLMNotConfigured, generate_script

router = APIRouter(prefix="/api/script", tags=["script"])


class ScriptRequest(BaseModel):
    topic: str = Field(min_length=1)
    tone: str = "neutral"
    length: str = "medium"
    lang: str = "zh"


@router.get("/status")
async def script_status(request: Request, refresh: bool = False) -> dict:
    """Live connectivity report — what the UI's "通没通" chip reads.

    It asks the endpoint instead of reading config, because "MONOLINE_LLM_* is set"
    and "a model will answer" are different facts. ?refresh=1 skips the probe cache.
    """
    import asyncio

    from ..llm.client import detect
    from ..settings import get_settings
    target = await asyncio.to_thread(detect, get_settings(), force=refresh)
    return target.as_dict()


@router.post("")
async def make_script(body: ScriptRequest, request: Request) -> dict:
    from ..settings import get_settings
    s = get_settings()
    try:
        script = await generate_script(s, body.topic, tone=body.tone, length=body.length, lang=body.lang)
    except LLMNotConfigured as e:
        raise HTTPException(503, str(e))
    except LLMError as e:
        raise HTTPException(502, str(e))
    return {"script": script, "beats": len([l for l in script.splitlines() if l.strip()])}
