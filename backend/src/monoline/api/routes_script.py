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
async def script_status(request: Request) -> dict:
    from ..settings import get_settings
    s = get_settings()
    return {"ready": s.llm_ready, "model": s.llm_model if s.llm_ready else None,
            "base_url": s.llm_base_url if s.llm_ready else None}


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
