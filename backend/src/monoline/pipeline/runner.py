"""Pipeline runner — executes the 9 M1 stages in order for one job.

M1 keeps this deliberately sequential + synchronous-in-order (async but one at a
time). Resumability via input_hash, SSE fan-out, sidecar render, and crash
reconcile land in M3. Durability is already real: every stage writes status +
segments + artifacts to SQLite, so a completed job's MP4 survives a restart.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path

from ..compose.engine import render_composition
from ..db.repo import Repo, now_iso
from ..fonts.subset import collect_glyphs, subset_font
from ..hf.cli import HF
from ..ir.sceneplan import Brand, Canvas, ScenePlan, Theme
from ..ir.timings import Timings
from ..voices import DEFAULT_VOICE
from ..settings import Settings
from .workspace import Workspace

Progress = Callable[[str, dict], Awaitable[None]]

STAGES = ["script", "tts", "assemble", "plan", "fonts", "compose", "gate", "render", "deliver"]

_MIME = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime"}


class JobCancelled(Exception):
    """Raised at a stage boundary when the user cancels a running job."""


def _h(*parts: object) -> str:
    return hashlib.sha256("⋄".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


async def _ffprobe_duration(path: Path) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    return float(out.decode().strip())


async def _ffprobe_streams(path: Path) -> list[str]:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    return [ln.strip() for ln in out.decode().splitlines() if ln.strip()]


def _slug(text: str, n: int = 24) -> str:
    keep = [c if c.isalnum() else "-" for c in text.lower()]
    s = "".join(keep).strip("-")
    s = "-".join(filter(None, s.split("-")))
    return s[:n] or "untitled"


async def run_pipeline(repo: Repo, settings: Settings, job_id: str, *, progress: Progress | None = None,
                       force: bool = False, only: str | None = None,
                       cancel: asyncio.Event | None = None) -> None:
    job = await repo.get_job(job_id)
    if not job:
        raise KeyError(job_id)
    ws = Workspace(settings.workspaces_dir / job_id).ensure()
    hf = HF(settings)
    config = json.loads(job["config_json"])
    canvas = json.loads(job["canvas_json"])
    voice = config.get("voice", DEFAULT_VOICE)
    lang = config.get("lang", "zh")
    speed = float(config.get("speed", 1.0))
    emit = progress or (lambda s, d: asyncio.sleep(0))

    await repo.update_job(job_id, status="running", started_at=now_iso())
    ctx: dict = {"slug": job.get("slug") or job_id}

    async def log(stage_key: str, message: str, *, level: str = "info", data: dict | None = None) -> None:
        await repo.add_event(job_id, "log", stage_key=stage_key, level=level, message=message, data=data)
        if emit:
            await emit(stage_key, {"stage": stage_key, "status": "running", "message": message, **(data or {})})

    async def stage(key: str, seq: int, fn, *, ihash: str, ready: Callable[[], bool] | None = None):
        if only and key != only:
            return None
        if cancel is not None and cancel.is_set():
            await repo.update_job(job_id, status="cancelled", finished_at=now_iso())
            await repo.add_event(job_id, "stage_finished", stage_key=key, level="warn", message="cancelled")
            raise JobCancelled(key)
        prior = await repo.get_stage(job_id, key)
        if (not force and prior and prior["status"] == "succeeded" and prior.get("input_hash") == ihash
                and (ready is None or ready())):
            await emit(key, {"stage": key, "status": "skipped"})
            await repo.add_event(job_id, "stage_finished", stage_key=key, message="skipped (cached)")
            return json.loads(prior["output_json"]) if prior.get("output_json") else {"skipped": True}
        await repo.upsert_stage(job_id, key, seq, status="running", started_at=now_iso(), input_hash=ihash)
        await repo.add_event(job_id, "stage_started", stage_key=key, message=key)
        await emit(key, {"stage": key, "status": "running"})
        try:
            out = await fn()
            await repo.upsert_stage(job_id, key, seq, status="succeeded",
                                    finished_at=now_iso(), output_json=json.dumps(out or {}, ensure_ascii=False))
            await repo.add_event(job_id, "stage_finished", stage_key=key, message=key)
            await emit(key, {"stage": key, "status": "succeeded", "result": out})
            return out
        except Exception as e:  # noqa: BLE001
            await repo.upsert_stage(job_id, key, seq, status="failed", finished_at=now_iso(), error=str(e))
            await repo.update_job(job_id, status="failed", error=f"{key}: {e}", finished_at=now_iso())
            await repo.add_event(job_id, "stage_finished", stage_key=key, level="error", message=str(e))
            await emit(key, {"stage": key, "status": "failed", "error": str(e)})
            raise

    # 1 script -----------------------------------------------------------------
    async def s_script():
        from .segment import segment_text
        beats = segment_text(job["script_text"])
        if not beats:
            raise ValueError("script is empty")
        rows = [{"i": i, "text": t, "line_no": i + 1} for i, t in enumerate(beats)]
        await repo.replace_segments(job_id, rows)
        slug = _slug(beats[0])
        ctx["slug"] = slug
        await repo.update_job(job_id, title=beats[0][:48], slug=slug)
        return {"beats": len(beats)}

    # 2 tts --------------------------------------------------------------------
    async def s_tts():
        segs = await repo.get_segments(job_id)
        durs: list[float] = []
        reused = 0
        for s in segs:
            linef = ws.tts / f"line_{s['i']:03d}.txt"
            wav = ws.tts / f"seg_{s['i']:03d}.wav"
            prev = linef.read_text(encoding="utf-8") if linef.exists() else None
            # per-beat cache: reuse the wav if the exact text/voice/speed is unchanged
            if (wav.exists() and prev == s["text"] and s.get("tts_duration")
                    and s.get("voice") == voice and s.get("speed") == speed):
                durs.append(float(s["tts_duration"]))
                reused += 1
                continue
            linef.write_text(s["text"], encoding="utf-8")
            await log("tts", f"合成第 {s['i']+1}/{len(segs)} 拍 · {s['text'][:16]}…",
                      data={"beat": s["i"], "of": len(segs)})
            payload = await hf.tts(str(linef), str(wav), voice=voice, lang=lang, speed=speed)
            dur = float(payload.get("durationSeconds") or await _ffprobe_duration(wav))
            durs.append(dur)
            await log("tts", f"  ✓ 第 {s['i']+1} 拍 · {dur:.1f}s", data={"beat": s["i"], "dur": dur})
            await repo.db.execute(
                "UPDATE segments SET wav_path=?, wav_bytes=?, tts_duration=?, voice=?, lang=?, speed=? WHERE job_id=? AND i=?",
                (str(wav), wav.stat().st_size, dur, voice, lang, speed, job_id, s["i"]),
            )
            await repo.db.commit()
        if reused:
            await log("tts", f"复用 {reused}/{len(segs)} 拍已有语音（文本未变）")
        return {"beats": len(durs), "audio_seconds": round(sum(durs), 3), "reused": reused}

    # 3 assemble ---------------------------------------------------------------
    async def s_assemble():
        segs = await repo.get_segments(job_id)
        concat = ws.tts / "concat.txt"
        concat.write_text("".join(f"file '{s['wav_path']}'\n" for s in segs), encoding="utf-8")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-c", "copy", str(ws.narration_wav),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {err.decode()[-400:]}")
        total = await _ffprobe_duration(ws.narration_wav)
        timings = Timings.from_durations([s["text"] for s in segs], [s["tts_duration"] for s in segs])
        (ws.ir / "timings.json").write_text(timings.model_dump_json(indent=2), encoding="utf-8")
        for sgm in timings.segments:
            await repo.db.execute("UPDATE segments SET start=?, end=? WHERE job_id=? AND i=?",
                                  (sgm.start, sgm.end, job_id, sgm.i))
        await repo.db.commit()
        await repo.update_job(job_id, total_duration=timings.total)
        return {"total": timings.total, "narration_bytes": ws.narration_wav.stat().st_size,
                "within_audio": abs(total - timings.total) < 0.12}

    # 4 plan -------------------------------------------------------------------
    async def s_plan():
        from .planner import RulePlanner
        from ..themes import resolve as resolve_theme
        segs = await repo.get_segments(job_id)
        theme = resolve_theme(settings, config)
        beats = [s["text"] for s in segs]
        scenes = RulePlanner().plan(beats, brand=config.get("brand", "Monoline"))
        plan = ScenePlan(job_id=job_id, canvas=Canvas(**canvas), theme=theme,
                         brand=Brand(label=config.get("brand", "Monoline")), scenes=scenes)
        warnings = plan.validate_against(len(beats))
        (ws.ir / "scene_plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        ver = await repo.save_plan(job_id, plan.model_dump_json(), "rules", warnings)
        kinds = {}
        for sc in scenes:
            kinds[sc["kind"]] = kinds.get(sc["kind"], 0) + 1
        return {"scenes": len(beats), "plan_version": ver, "kinds": kinds, "warnings": warnings}

    # 5 fonts ------------------------------------------------------------------
    async def s_fonts():
        segs = await repo.get_segments(job_id)
        plan_row = await repo.get_plan(job_id)
        plan = ScenePlan.model_validate_json(plan_row["plan_json"])
        texts = [s["text"] for s in segs] + [str(v) for sc in plan.scenes for v in _flat(sc.slots)]
        glyphs = collect_glyphs(texts, brand=plan.brand.label)
        res = subset_font(glyphs, ws.font_woff2, cache_dir=settings.cache_dir / "fonts")
        shutil.copy(settings.vendor_dir / "fonts" / "OFL.txt", ws.comp_fonts / "LICENSE-OFL.txt")
        if res.missing:
            # Don't fail: the subset holds every glyph the font has; the rest (emoji,
            # rare symbols, other scripts) render via the browser's system fallback.
            await log("fonts", f"字体缺字 {len(res.missing)} 个，将由系统字体回退渲染（不影响出片）",
                      level="warn", data={"missing": res.missing[:12]})
        return {"glyphs": res.glyphs, "bytes": res.bytes, "cached": res.cached, "missing": len(res.missing)}

    # 6 compose ----------------------------------------------------------------
    async def s_compose():
        from .audio_mix import ensure_voice_track
        segs = await repo.get_segments(job_id)
        timings = Timings.model_validate_json((ws.ir / "timings.json").read_text())
        # DB plan is the source of truth (manual Studio edits land there); the ir
        # file is only the rules-planner's initial copy and can be stale after edits.
        plan_row = await repo.get_plan(job_id)
        plan_src = plan_row["plan_json"] if plan_row else (ws.ir / "scene_plan.json").read_text()
        plan = ScenePlan.model_validate_json(plan_src)
        vo_src = await ensure_voice_track(ws, config, timings.total)
        html = render_composition(timings, plan, title=job["title"] or "", vo_src=vo_src)
        ws.index_html.write_text(html, encoding="utf-8")
        # vendor gsap + scaffold project files (relative paths only)
        shutil.copy(settings.vendor_dir / "gsap.min.js", ws.comp_vendor / "gsap.min.js")
        shutil.copy(settings.vendor_dir / "gsap-LICENSE.txt", ws.comp_vendor / "gsap-LICENSE.txt")
        _write_hf_project(ws.composition, job_id, job["title"] or "monoline", settings)
        await repo.add_artifact(job_id, kind="composition_html", stage_key="compose",
                                rel_path="composition/index.html", abs_path=str(ws.index_html),
                                mime="text/html", size_bytes=ws.index_html.stat().st_size)
        return {"html_bytes": len(html)}

    # 7 gate (lint only in M1) -------------------------------------------------
    async def s_gate():
        ok, data = await hf.lint(str(ws.composition))
        (ws.gate / "lint.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if not ok:
            raise RuntimeError(f"lint failed: {_lint_summary(data)}")
        return {"lint": "pass"}

    # 8 render -----------------------------------------------------------------
    async def s_render():
        from ..hf.cli import SidecarUnavailableError
        fmt = config.get("format", "mp4")
        out = ws.renders / f"{ctx['slug']}.{fmt}"
        fps = canvas.get("fps", 30)
        quality = config.get("quality", "standard")
        via = "sidecar" if settings.render_via_sidecar else "cli"
        await log("render", f"启动 HyperFrames 渲染（{via} · {fmt} · 无头 Chrome 逐帧捕获 + FFmpeg 编码）…")
        try:
            if settings.render_via_sidecar:
                try:
                    await hf.render_via_sidecar(str(ws.composition), str(out), fps=fps, quality=quality, fmt=fmt)
                except SidecarUnavailableError as e:
                    await log("render", f"sidecar 不可用（{e}），回退 CLI 渲染…", level="warn")
                    await hf.render(str(ws.composition), str(out), fps=fps, quality=quality, fmt=fmt)
            else:
                await hf.render(str(ws.composition), str(out), fps=fps, quality=quality, fmt=fmt)
        except Exception as e:  # noqa: BLE001 — surface which path failed
            raise RuntimeError(f"render via {via} failed: {e}") from e
        ctx["render_out"] = str(out)
        await log("render", f"渲染完成 → {out.name}")
        return {"video": str(out), "via": via, "format": fmt}

    # 9 deliver ----------------------------------------------------------------
    async def s_deliver():
        fmt = config.get("format", "mp4")
        out = Path(ctx.get("render_out") or (ws.renders / f"{ctx['slug']}.{fmt}"))
        streams = await _ffprobe_streams(out)
        dur = await _ffprobe_duration(out)
        fresh = await repo.get_job(job_id)  # total_duration set during assemble; local `job` is stale
        total = fresh.get("total_duration")
        if "audio" not in streams:
            raise RuntimeError("render has NO audio stream (silent video bug)")
        if total is not None and abs(dur - total) > 0.15:
            raise RuntimeError(f"render duration {dur} != narration {total}")
        await repo.add_artifact(job_id, kind="render_mp4", stage_key="deliver", rel_path=f"renders/{out.name}",
                                abs_path=str(out), mime=_MIME.get(fmt, "video/mp4"), size_bytes=out.stat().st_size,
                                duration_seconds=dur, fps=canvas.get("fps", 30),
                                width=canvas.get("width"), height=canvas.get("height"))
        return {"video": str(out), "duration": dur, "streams": streams, "format": fmt}

    # input hashes (stable inputs) + output-existence predicates → resumable
    st = job["script_text"]
    av = _h(st, voice, lang, speed)
    _b = config.get("bgm")
    bg = json.dumps(_b, sort_keys=True) if _b else ""
    fmt = config.get("format", "mp4")

    async def _plan_json() -> str:
        r = await repo.get_plan(job_id)
        return r["plan_json"] if r else ""

    async def _segs_count() -> int:
        return len(await repo.get_segments(job_id))

    def _all_wavs(n: int) -> bool:
        return all((ws.tts / f"seg_{i:03d}.wav").exists() for i in range(n))

    def _any_render() -> bool:
        return any((ws.renders / f"{ctx['slug']}.{e}").exists() for e in _MIME)

    await stage("script", 0, s_script, ihash=_h(st), ready=lambda: True)
    n = await _segs_count()
    await stage("tts", 1, s_tts, ihash=av, ready=lambda: _all_wavs(n))
    await stage("assemble", 2, s_assemble, ihash=av, ready=lambda: ws.narration_wav.exists())
    await stage("plan", 3, s_plan, ihash=_h(st, config.get("brand"), config.get("theme"), config.get("accent")), ready=lambda: bool(ws.ir.joinpath("scene_plan.json").exists()))
    pj = await _plan_json()
    await stage("fonts", 4, s_fonts, ihash=_h(pj), ready=lambda: ws.font_woff2.exists())
    await stage("compose", 5, s_compose, ihash=_h(pj, st, bg), ready=lambda: ws.index_html.exists())
    await stage("gate", 6, s_gate, ihash=_h(pj, bg), ready=lambda: (ws.gate / "lint.json").exists())
    await stage("render", 7, s_render, ihash=_h(pj, st, bg, fmt), ready=_any_render)
    await stage("deliver", 8, s_deliver, ihash=_h(pj, bg, fmt), ready=_any_render)

    # Terminal status lives here, not inside a stage: a cached re-run (double enqueue,
    # resume, or reconcile of an already-finished job) short-circuits every stage incl.
    # deliver, so writing "succeeded" only from s_deliver left such jobs stuck "running"
    # forever — which then re-reconciled on every restart. This runs on any clean exit.
    await repo.update_job(job_id, status="succeeded", finished_at=now_iso())


def _flat(d: dict) -> list:
    out = []
    for v in d.values():
        if isinstance(v, dict):
            out.extend(_flat(v))
        elif isinstance(v, list):
            out.extend(x for x in v if isinstance(x, str))
        elif isinstance(v, str):
            out.append(v)
    return out


def _lint_summary(data: dict) -> str:
    findings = data.get("findings") or []
    errs = [f for f in findings if f.get("severity") == "error"] or findings
    return json.dumps(errs[:8], ensure_ascii=False)[:800]


def _write_hf_project(comp_dir: Path, job_id: str, name: str, settings: Settings) -> None:
    (comp_dir / "hyperframes.json").write_text(
        json.dumps({
            "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
            "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
            "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
            "media": {"autoProxy": True},
        }, indent=2), encoding="utf-8")
    (comp_dir / "meta.json").write_text(
        json.dumps({"id": job_id, "name": name, "createdAt": now_iso()}), encoding="utf-8")
    (comp_dir / "package.json").write_text(
        json.dumps({"name": name, "private": True, "type": "module", "scripts": {
            "render": f"npx --yes hyperframes@{settings.hf_version} render"}}, indent=2), encoding="utf-8")
