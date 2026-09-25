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


class PreviewRequest(BaseModel):
    script: str = Field(default="")


@router.post("/preview")
async def script_preview(body: PreviewRequest) -> dict:
    """Beat count for a script, from the real segmenter.

    The NewView estimate used to be a second, simpler implementation of segmentation in
    TypeScript, and it disagreed with the pipeline on 30% of stored scripts — always
    low, because it never applied the long-sentence clause split or the tiny-beat merge
    (worst measured case: UI said 6, the job made 17). One owner instead of a port.

    `over_cap` is a verdict, not a message: the UI has to phrase it in zh and en, so the
    route reports numbers (beats vs cap) and lets the caller do the prose. Counting runs
    with the guard off — a paste past the cap still has to come back with its real number,
    which is the whole point of warning before Generate rather than after.
    """
    import asyncio

    from ..pipeline.segment import HARD_CAP, SECONDS_PER_BEAT, segment_text

    def count() -> int:
        return len(segment_text(body.script, hard_cap=None))

    beats = await asyncio.to_thread(count)
    return {"beats": beats, "chars": len(body.script), "seconds": round(beats * SECONDS_PER_BEAT),
            "cap": HARD_CAP, "over_cap": beats > HARD_CAP}
