"""Jobs API — the frontend's contract. M1: create, hydrate, list, run, download."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import brand
from ..voices import DEFAULT_VOICE

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class CreateJob(BaseModel):
    script: str = Field(min_length=1)
    voice: str = DEFAULT_VOICE
    # phonemizer lang is always derived from the voice (see create_job), not sent in
    speed: float = Field(default=1.0, ge=0.7, le=1.2)
    quality: str = "standard"
    ratio: str = "landscape"
    layout: str = "minimal"
    fps: int = Field(default=30, ge=1, le=60)
    format: str = "mp4"
    # appearance identity is optional here: whatever is omitted comes from the
    # user-level brand store (GET /api/brand), not from a hardcoded default
    theme: str | None = None
    accent: str | None = None
    brand: str | None = None
    llm_plan: bool = True   # let a connected model re-judge the beats the rules call plain text


_RATIOS = {"landscape": (1920, 1080), "portrait": (1080, 1920), "square": (1080, 1080)}
_QUALITIES = {"draft", "looks", "delivery", "standard", "high"}
_FORMATS = {"mp4", "webm", "mov"}
_LAYOUTS = {"minimal", "editorial", "bold"}


def _manager(request: Request):
    m = getattr(request.app.state, "manager", None)
    if not m:
        raise HTTPException(503, "job manager not ready")
    return m


@router.post("")
async def create_job(body: CreateJob, request: Request) -> dict:
    from ..pipeline.segment import segment_text
    from ..voices import is_known_voice, voice_lang

    m = _manager(request)
    if not is_known_voice(body.voice):
        raise HTTPException(422, f"unknown voice {body.voice!r}")
    # V47: run the beat-count guard at intake. Assemble raises the same ValueError later, but
    # by then the job exists, shows as running, and the user has watched TTS synthesise a
    # script that could never render. Segmentation is CPU work → off the event loop.
    try:
        await asyncio.to_thread(segment_text, body.script)
    except ValueError as e:
        raise HTTPException(422, str(e))
    w, h = _RATIOS.get(body.ratio, _RATIOS["landscape"])
    quality = body.quality if body.quality in _QUALITIES else "standard"
    fmt = body.format if body.format in _FORMATS else "mp4"
    layout = body.layout if body.layout in _LAYOUTS else "minimal"
    # lang is derived from the voice so the phonemizer can never drift from it
    config = {"voice": body.voice, "lang": voice_lang(body.voice), "speed": body.speed,
              "quality": quality, "format": fmt, "layout": layout, "llm_plan": bool(body.llm_plan)}
    for key, val in (("brand", body.brand), ("theme", body.theme), ("accent", body.accent)):
        if val:
            config[key] = val.strip() if isinstance(val, str) else val
    brand.apply_to_config(m.settings, config)      # user identity fills what's missing
    logo = config.pop("logo", "")
    jid = await m.create_job(script=body.script, config=config, canvas={"width": w, "height": h, "fps": body.fps},
                             start=False)
    if logo:
        rel = brand.freeze_logo_into(m.settings, jid, logo)
        if rel:
            job = await m.repo.get_job(jid)
            cfg = json.loads(job["config_json"])
            cfg["logo"] = rel
            await m.repo.update_job(jid, config_json=cfg)
    await m.enqueue(jid)
    return {"job_id": jid}


@router.get("")
async def list_jobs(request: Request, limit: int = 50) -> dict:
    m = _manager(request)
    jobs = await m.repo.list_jobs(limit=limit)
    return {"jobs": [{k: j.get(k) for k in ("id", "slug", "title", "status", "total_duration", "created_at")} for j in jobs]}


@router.get("/{jid}")
async def get_job(jid: str, request: Request) -> dict:
    m = _manager(request)
    job = await m.repo.get_job(jid)
    if not job:
        raise HTTPException(404, "job not found")
    stages = await m.repo.get_stages(jid)
    segments = await m.repo.get_segments(jid)
    artifacts = await m.repo.get_artifacts(jid)
    plan = await m.repo.get_plan(jid)
    events = await m.repo.get_events_since(jid, 0)
    return {
        "job": {k: job.get(k) for k in ("id", "slug", "title", "status", "total_duration", "config_json", "canvas_json", "error")},
        "stages": [{k: s.get(k) for k in ("key", "seq", "status", "error")} for s in stages],
        "segments": [{k: s.get(k) for k in ("i", "start", "end", "norm_duration", "text")} for s in segments],
        "artifacts": [{k: a.get(k) for k in ("id", "kind", "rel_path", "mime", "size_bytes", "duration_seconds", "state")} for a in artifacts],
        # `warnings` used to be written to the DB and never read back by anyone: a plan-quality
        # signal the pipeline computes has to reach the client for the field to mean anything.
        "plan": ({**json.loads(plan["plan_json"]),
                  "warnings": json.loads(plan["warnings_json"] or "[]")} if plan else None),
        "events": [{"id": e["id"], "stage": e.get("stage_key"), "kind": e["kind"],
                    "level": e.get("level"), "message": e.get("message")} for e in events][-120:],
    }


@router.get("/{jid}/events")
async def job_events(jid: str, request: Request, after: int = 0) -> dict:
    """Poll-friendly event tail. The live path is /stream SSE; this one exists for
    `monoline` CLI users and for debugging a job without opening the browser."""
    m = _manager(request)
    events = await m.repo.get_events_since(jid, after)
    return {"events": [{"id": e["id"], "stage": e.get("stage_key"), "kind": e["kind"],
                        "level": e.get("level"), "message": e.get("message"),
                        "data": json.loads(e["data_json"]) if e.get("data_json") else None}
                       for e in events]}


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@router.get("/{jid}/stream")
async def job_stream(jid: str, request: Request) -> StreamingResponse:
    """Server-Sent Events: live stage transitions + a terminal ``done`` frame, so the
    Studio updates without 1.2s polling. Sends a status snapshot first (late joiners),
    then pushes from the manager's per-job bus. Keepalives guard idle proxies."""
    m = _manager(request)
    job = await m.repo.get_job(jid)
    if not job:
        raise HTTPException(404, "job not found")

    async def gen():
        q = m.subscribe(jid)
        try:
            yield _sse({"type": "snapshot", "status": job["status"]})
            if job["status"] in ("succeeded", "failed", "cancelled"):
                yield _sse({"type": "done", "status": job["status"]})
                return
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _sse(payload)
                if payload.get("type") == "done":
                    break
        finally:
            m.unsubscribe(jid, q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.post("/{jid}/run")
async def run_job(jid: str, request: Request, force: bool = False) -> dict:
    m = _manager(request)
    if not await m.repo.get_job(jid):
        raise HTTPException(404, "job not found")
    await m.enqueue(jid, force=force)
    return {"job_id": jid, "queued": True, "force": force}


@router.post("/{jid}/cancel")
async def cancel_job(jid: str, request: Request) -> dict:
    m = _manager(request)
    ok = m.cancel(jid)
    if ok:
        await m.repo.add_event(jid, "notice", level="warn", message="cancel requested")
    return {"job_id": jid, "cancelling": ok}


@router.delete("/{jid}")
async def delete_job(jid: str, request: Request, purge_files: bool = True) -> dict:
    import shutil

    m = _manager(request)
    job = await m.repo.get_job(jid)
    if not job:
        raise HTTPException(404, "job not found")
    if purge_files:
        shutil.rmtree(m.settings.workspaces_dir / jid, ignore_errors=True)
    await m.repo.db.execute("DELETE FROM jobs WHERE id=?", (jid,))
    await m.repo.db.commit()
    return {"deleted": jid}


@router.get("/{jid}/download")
async def download(jid: str, request: Request) -> FileResponse:
    m = _manager(request)
    arts = await m.repo.get_artifacts(jid)
    mp4 = next((a for a in arts if a["kind"] == "render_mp4" and a["state"] == "local"), None)
    if not mp4 or not Path(mp4["abs_path"]).exists():
        raise HTTPException(404, "no rendered file yet")
    return FileResponse(mp4["abs_path"], media_type=mp4.get("mime") or "video/mp4",
                        filename=Path(mp4["abs_path"]).name)


_SUB_MIME = {"srt": "application/x-subrip", "vtt": "text/vtt"}


@router.get("/{jid}/subtitles")
async def subtitles(jid: str, request: Request, fmt: str = "srt"):
    """Download a subtitle sidecar (srt|vtt) built from the beat timings."""
    from fastapi.responses import PlainTextResponse

    from ..pipeline.subtitles import to_srt, to_vtt

    m = _manager(request)
    job = await m.repo.get_job(jid)
    if not job:
        raise HTTPException(404, "job not found")
    if fmt not in _SUB_MIME:
        raise HTTPException(422, f"unsupported subtitle format {fmt!r}")
    segs = await m.repo.get_segments(jid)
    if not segs:
        raise HTTPException(409, "no beats yet — run the job first")
    body = to_srt(segs) if fmt == "srt" else to_vtt(segs)
    slug = job.get("slug") or jid
    # slug can be CJK → not latin-1 encodable as a raw header. ASCII fallback + RFC 5987.
    from urllib.parse import quote
    disp = f'attachment; filename="subtitles.{fmt}"; filename*=UTF-8\'\'{quote(f"{slug}.{fmt}")}'
    return PlainTextResponse(body, media_type=_SUB_MIME[fmt], headers={"Content-Disposition": disp})


@router.get("/{jid}/poster")
async def poster(jid: str, request: Request):
    """Cover frame extracted on demand from the rendered video (cached to
    renders/poster.jpg, so it also backfills jobs rendered before this feature)."""
    from ..pipeline.workspace import Workspace

    m = _manager(request)
    job = await m.repo.get_job(jid)
    if not job:
        raise HTTPException(404, "job not found")
    arts = await m.repo.get_artifacts(jid)
    vid = next((a for a in arts if a["kind"] == "render_mp4" and a["state"] == "local"), None)
    if not vid or not Path(vid["abs_path"]).exists():
        raise HTTPException(409, "no rendered video yet")
    ws = Workspace(m.settings.workspaces_dir / jid).ensure()
    out = ws.renders / "poster.jpg"
    if not out.exists():
        total = float(job.get("total_duration") or 0.0)
        ts = min(1.2, total * 0.5) if total else 0.0  # skip the black intro fade
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-v", "error", "-y", "-ss", f"{ts:.3f}", "-i", vid["abs_path"],
            "-frames:v", "1", "-q:v", "2", str(out),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0 or not out.exists():
            raise HTTPException(500, f"poster extract failed: {err.decode()[-200:]}")
    from urllib.parse import quote
    slug = job.get("slug") or jid
    disp = f'inline; filename="poster.jpg"; filename*=UTF-8\'\'{quote(f"{slug}.jpg")}'
    return FileResponse(out, media_type="image/jpeg", headers={"Content-Disposition": disp})


class ScenePatch(BaseModel):
    kind: str | None = None
    slots: dict | None = None
    # Who decided this.  The badge under the mode picker reads "rules:…" until someone touches
    # the beat, and "llm:adopt" when the touch was a model suggestion the user accepted.
    source: str | None = None


@router.patch("/{jid}/plan/scenes/{i}")
async def patch_scene(jid: str, i: int, body: ScenePatch, request: Request) -> dict:
    """Edit one beat's kind/slots → new plan version → recompose (preview refresh, no re-render)."""
    from ..pipeline.recompose import recompose

    m = _manager(request)
    plan_row = await m.repo.get_plan(jid)
    if not plan_row:
        raise HTTPException(409, "no plan yet — run the job first")
    plan = json.loads(plan_row["plan_json"])
    scenes = plan.get("scenes", [])
    if i < 0 or i >= len(scenes):
        raise HTTPException(404, "scene index out of range")
    if body.kind is not None:
        scenes[i]["kind"] = body.kind
    if body.slots is not None:
        scenes[i]["slots"] = body.slots
    if body.source is not None:
        if body.source not in ("manual", "llm:adopt"):
            raise HTTPException(422, f"unknown source {body.source!r}")
        scenes[i]["source"] = body.source
    new_json = json.dumps(plan, ensure_ascii=False)
    # validate scenes vs segments count
    segs = await m.repo.get_segments(jid)
    try:
        from ..ir.sceneplan import ScenePlan
        ScenePlan.model_validate_json(new_json).validate_against(len(segs))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, str(e))
    ver = await m.repo.save_plan(jid, new_json, "manual", [])
    result = await recompose(m.repo, m.settings, jid)
    return {"version": ver, **result}


class ReorderBody(BaseModel):
    order: list[int]


@router.post("/{jid}/plan/scenes/{i}/suggest")
async def suggest_scene(jid: str, i: int, request: Request) -> dict:
    """Ask the model about ONE beat and return its verdict **without applying it**.

    Measured on the local model: 0.3–0.85 characters/second of decode, so a beat with a real
    answer costs 40–70s and a whole-script upgrade pass cannot finish inside any sane timeout
    (docs/PLAN.md V55).  One beat per click is the only shape of "let the model design layouts"
    that fits that speed — and because the user starts it, the wait is expected, not a stuck job.
    """
    from ..llm.client import detect
    from ..llm.planner import upgrade

    m = _manager(request)
    if not await m.repo.get_job(jid):
        raise HTTPException(404, "job not found")
    plan_row = await m.repo.get_plan(jid)
    segs = await m.repo.get_segments(jid)
    if not plan_row or not segs:
        raise HTTPException(409, "no plan yet — run the job first")
    plan = json.loads(plan_row["plan_json"])
    scenes = plan.get("scenes", [])
    if i < 0 or i >= len(scenes) or i >= len(segs):
        raise HTTPException(404, "scene index out of range")
    target = await asyncio.to_thread(detect, m.settings)
    if not target.ok:
        raise HTTPException(503, target.detail or "LLM 不可用")
    out, stats = await upgrade(m.settings, [segs[i]["text"]], [dict(scenes[i])],
                               target=target, force=True)
    cand = out[0]
    return {"model": stats.get("model"), "seconds": stats.get("seconds"),
            "kind": cand.get("kind"), "slots": cand.get("slots"),
            "same": cand.get("kind") == scenes[i].get("kind"),
            "why": stats.get("why") or []}


@router.post("/{jid}/reorder")
async def reorder_beats(jid: str, body: ReorderBody, request: Request) -> dict:
    """Permute the beats (drag-reorder in Studio). Carries each beat's cached audio,
    re-concats + re-times narration, reorders the plan, recomposes — no re-TTS."""
    from ..pipeline.recompose import reorder

    m = _manager(request)
    try:
        return await reorder(m.repo, m.settings, jid, body.order)
    except KeyError:
        raise HTTPException(404, "job not found")
    except ValueError as e:
        raise HTTPException(422, str(e))


class SegmentPatch(BaseModel):
    text: str = Field(min_length=1)


@router.patch("/{jid}/segments/{i}")
async def patch_segment(jid: str, i: int, body: SegmentPatch, request: Request) -> dict:
    """Edit one beat's NARRATION text → re-TTS that beat + re-time + recompose.

    Slower than a slide-text edit (one TTS call ~2-5s + re-concat), but keeps audio
    and captions in sync with the new wording.
    """
    from ..pipeline.recompose import resynth_segment

    m = _manager(request)
    try:
        return await resynth_segment(m.repo, m.settings, jid, i, body.text)
    except IndexError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


class VoiceBody(BaseModel):
    voice: str


@router.post("/{jid}/voice")
async def change_voice(jid: str, body: VoiceBody, request: Request) -> dict:
    """Swap the narration voice for a composed job → re-TTS every beat with the new
    voice (text/plan unchanged) + re-concat + re-time + recompose. Slower than a visual
    edit (one TTS call per beat, ~2-5s each), so the Studio shows a re-synth busy state."""
    from ..pipeline.recompose import revoice

    m = _manager(request)
    try:
        return await revoice(m.repo, m.settings, jid, body.voice)
    except KeyError:
        raise HTTPException(404, "job not found")
    except ValueError as e:
        raise HTTPException(422, str(e))


_ALLOWED_BGM = {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}


@router.post("/{jid}/bgm")
async def upload_bgm(jid: str, request: Request, file: UploadFile = File(...),
                     volume: float = Form(0.22), duck: bool = Form(True)) -> dict:
    """Attach a background-music track to the job (mixed under narration)."""
    from ..pipeline.recompose import recompose

    m = _manager(request)
    job = await m.repo.get_job(jid)
    if not job:
        raise HTTPException(404, "job not found")
    suffix = Path(file.filename or "bgm").suffix.lower()
    if suffix not in _ALLOWED_BGM:
        raise HTTPException(422, f"unsupported audio type {suffix!r}")
    from ..pipeline.workspace import Workspace
    ws = Workspace(m.settings.workspaces_dir / jid).ensure()
    # replace any prior bed of a different extension
    for old in ws.comp_audio.glob("bgm.*"):
        old.unlink(missing_ok=True)
    bgm_path = ws.comp_audio / f"bgm{suffix}"
    bgm_path.write_bytes(await file.read())
    config = json.loads(job["config_json"])
    config["bgm"] = {"src": f"audio/bgm{suffix}", "volume": max(0.0, min(0.6, volume)), "duck": bool(duck)}
    await m.repo.update_job(jid, config_json=config)
    result = await recompose(m.repo, m.settings, jid)
    return {"bgm": config["bgm"], **result}


@router.delete("/{jid}/bgm")
async def remove_bgm(jid: str, request: Request) -> dict:
    from ..pipeline.recompose import recompose

    m = _manager(request)
    job = await m.repo.get_job(jid)
    if not job:
        raise HTTPException(404, "job not found")
    config = json.loads(job["config_json"])
    config.pop("bgm", None)
    await m.repo.update_job(jid, config_json=config)
    from ..pipeline.workspace import Workspace
    ws = Workspace(m.settings.workspaces_dir / jid)
    for p in (ws.comp_audio / "bgm.mp3").parent.glob("bgm.*"):
        p.unlink(missing_ok=True)
    result = await recompose(m.repo, m.settings, jid)
    return {"removed": True, **result}


_ALLOWED_IMG = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MAX_IMG = 12 * 1024 * 1024


@router.post("/{jid}/assets")
async def upload_asset(jid: str, request: Request, file: UploadFile = File(...)) -> dict:
    """Freeze an image into the job workspace (composition/assets) and return its
    composition-relative path. SVG is rejected (script surface); the filename is a
    content hash so a new image always changes the plan hash and re-renders."""
    import hashlib

    m = _manager(request)
    job = await m.repo.get_job(jid)
    if not job:
        raise HTTPException(404, "job not found")
    suffix = Path(file.filename or "img").suffix.lower()
    if suffix not in _ALLOWED_IMG:
        raise HTTPException(422, f"unsupported image type {suffix!r}")
    data = await file.read()
    if not data:
        raise HTTPException(422, "empty file")
    if len(data) > _MAX_IMG:
        raise HTTPException(413, f"image too large ({len(data)} bytes, max {_MAX_IMG})")
    from ..pipeline.workspace import Workspace
    ws = Workspace(m.settings.workspaces_dir / jid).ensure()
    rel = f"assets/{hashlib.sha1(data).hexdigest()[:16]}{suffix}"
    (ws.composition / rel).write_bytes(data)
    return {"rel": rel, "bytes": len(data)}


@router.post("/{jid}/logo")
async def upload_logo(jid: str, request: Request, file: UploadFile = File(...)) -> dict:
    """Freeze a brand logo into the composition and show it in the #brand lockup
    (re-skin + recompose → preview refresh; render picks it up via the plan hash)."""
    import hashlib

    from ..pipeline.recompose import retheme
    from ..pipeline.workspace import Workspace

    m = _manager(request)
    job = await m.repo.get_job(jid)
    if not job:
        raise HTTPException(404, "job not found")
    suffix = Path(file.filename or "logo").suffix.lower()
    if suffix not in _ALLOWED_IMG:
        raise HTTPException(422, f"unsupported image type {suffix!r}")
    data = await file.read()
    if not data:
        raise HTTPException(422, "empty file")
    if len(data) > _MAX_IMG:
        raise HTTPException(413, f"logo too large ({len(data)} bytes, max {_MAX_IMG})")
    ws = Workspace(m.settings.workspaces_dir / jid).ensure()
    for old in (ws.composition / "assets").glob("logo-*"):
        old.unlink(missing_ok=True)
    rel = f"assets/logo-{hashlib.sha1(data).hexdigest()[:12]}{suffix}"
    (ws.composition / rel).write_bytes(data)
    config = json.loads(job["config_json"])
    config["logo"] = rel
    await m.repo.update_job(jid, config_json=config)
    result = await retheme(m.repo, m.settings, jid)
    return {"logo": rel, **result}


@router.delete("/{jid}/logo")
async def remove_logo(jid: str, request: Request) -> dict:
    from ..pipeline.recompose import retheme
    from ..pipeline.workspace import Workspace

    m = _manager(request)
    job = await m.repo.get_job(jid)
    if not job:
        raise HTTPException(404, "job not found")
    config = json.loads(job["config_json"])
    config.pop("logo", None)
    await m.repo.update_job(jid, config_json=config)
    ws = Workspace(m.settings.workspaces_dir / jid)
    for p in (ws.composition / "assets").glob("logo-*"):
        p.unlink(missing_ok=True)
    result = await retheme(m.repo, m.settings, jid)
    return {"removed": True, **result}


class ConfigPatch(BaseModel):
    theme: str | None = None
    accent: str | None = None
    brand: str | None = None
    layout: str | None = None


@router.patch("/{jid}/config")
async def patch_config(jid: str, body: ConfigPatch, request: Request) -> dict:
    """Change theme/accent/brand/layout on a composed job → re-skin the plan in place +
    recompose (fast preview refresh; render later picks it up via the plan hash)."""
    from ..pipeline.recompose import retheme
    from ..themes import available

    m = _manager(request)
    job = await m.repo.get_job(jid)
    if not job:
        raise HTTPException(404, "job not found")
    config = json.loads(job["config_json"])
    if body.theme is not None:
        valid = {t["id"] for t in available(m.settings)}
        if body.theme not in valid:
            raise HTTPException(422, f"unknown theme {body.theme!r}")
        config["theme"] = body.theme
    if body.accent is not None:
        config["accent"] = body.accent if body.accent.strip() else None
    if body.brand is not None:
        config["brand"] = body.brand.strip() or "Monoline"
    if body.layout is not None:
        if body.layout not in _LAYOUTS:
            raise HTTPException(422, f"unknown layout {body.layout!r}")
        config["layout"] = body.layout
    await m.repo.update_job(jid, config_json=config)
    result = await retheme(m.repo, m.settings, jid)
    return {"config": {"theme": config.get("theme"), "accent": config.get("accent"),
                       "brand": config.get("brand"), "layout": config.get("layout")},
            **result}
