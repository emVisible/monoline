"""Re-compose / re-synth a job after edits.

- recompose(): fonts + compose + lint only (fast; slide-text edits, no audio change).
- resynth_segment(): narration text of one beat changed → re-TTS that beat, re-concat
  the narration track, re-time every beat, re-derive that scene's keyword, recompose.
"""
from __future__ import annotations

import asyncio
import json

from ..compose.engine import render_composition, vendor_composition_assets
from ..db.repo import Repo
from ..fonts.subset import collect_glyphs, subset_font
from ..hf.cli import HF
from ..ir.sceneplan import overlays_from_config
from ..ir.sceneplan import DIAGRAM_KINDS, ScenePlan
from ..ir.timings import Timings
from ..settings import Settings
from ..voices import DEFAULT_VOICE
from .planner import distill_keyword
from .runner import _flat, _ffprobe_duration
from .workspace import Workspace


async def recompose(repo: Repo, settings: Settings, job_id: str) -> dict:
    job = await repo.get_job(job_id)
    if not job:
        raise KeyError(job_id)
    ws = Workspace(settings.workspaces_dir / job_id).ensure()
    plan_row = await repo.get_plan(job_id)
    if not plan_row:
        raise ValueError("no plan to recompose")
    plan = ScenePlan.model_validate_json(plan_row["plan_json"])
    timings = Timings.model_validate_json((ws.ir / "timings.json").read_text())
    segs = await repo.get_segments(job_id)

    # fonts: rebuild the subset from the (possibly edited) plan text
    texts = [s["text"] for s in segs] + [str(v) for sc in plan.scenes for v in _flat(sc.slots)]
    glyphs = collect_glyphs(texts, brand=plan.brand.label)
    res = subset_font(glyphs, ws.font_woff2, cache_dir=settings.cache_dir / "fonts")
    if res.missing:
        return {"ok": False, "error": f"font missing glyphs: {res.missing[:8]}", "version": plan_row["version"]}

    # compose
    from .audio_mix import ensure_voice_track
    config = json.loads(job["config_json"])
    vo_src = await ensure_voice_track(ws, config, timings.total)
    html = render_composition(timings, plan, title=job["title"] or "", vo_src=vo_src,
                              layout=config.get("layout", "minimal"))
    ws.index_html.write_text(html, encoding="utf-8")
    vendor_composition_assets(ws, settings.vendor_dir, html)

    # lint (non-fatal; surfaced as warnings)
    hf = HF(settings)
    lint_ok, lint_data = await hf.lint(str(ws.composition))
    errors = [f for f in (lint_data.get("findings") or []) if f.get("severity") == "error"]

    return {
        "ok": lint_ok,
        "version": plan_row["version"],
        "html_bytes": len(html),
        "lint_errors": errors[:8],
    }


async def reorder(repo: Repo, settings: Settings, job_id: str, order: list[int]) -> dict:
    """Permute the beats. ``order`` is a permutation of the current segment indices —
    ``order[p]`` is the OLD index that becomes the beat at position ``p``. Rewrites the
    segment rows (carrying each beat's cached wav + duration, so NO re-TTS), re-concats
    the narration in the new order, re-times every beat, reorders the plan's scenes to
    match, then recomposes. Returns {version, total_duration, order}."""
    job = await repo.get_job(job_id)
    if not job:
        raise KeyError(job_id)
    segs = await repo.get_segments(job_id)
    n = len(segs)
    if sorted(order) != list(range(n)):
        raise ValueError(f"order must be a permutation of 0..{n - 1}")
    ws = Workspace(settings.workspaces_dir / job_id).ensure()

    # 1. rewrite segment rows in the new order (audio fields travel with each beat)
    rows = []
    for p, old in enumerate(order):
        s = segs[old]
        rows.append({"i": p, "text": s["text"], "line_no": p + 1, "wav_path": s["wav_path"],
                     "wav_bytes": s.get("wav_bytes"), "tts_duration": s["tts_duration"],
                     "audio_source": s.get("audio_source", "tts"), "voice": s.get("voice"),
                     "lang": s.get("lang"), "speed": s.get("speed")})
    await repo.replace_segments(job_id, rows)

    # 2. re-concat narration + re-time (running sum) — same as resynth_segment step 2
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
        raise RuntimeError(f"ffmpeg concat failed: {err.decode()[-300:]}")
    timings = Timings.from_durations([s["text"] for s in segs], [s["tts_duration"] for s in segs])
    (ws.ir / "timings.json").write_text(timings.model_dump_json(indent=2), encoding="utf-8")
    for sgm in timings.segments:
        await repo.db.execute("UPDATE segments SET start=?, end=? WHERE job_id=? AND i=?",
                              (sgm.start, sgm.end, job_id, sgm.i))
    await repo.db.commit()
    await repo.update_job(job_id, total_duration=timings.total)

    # 3. reorder the plan's scenes to match, renumber, save a new version
    plan_row = await repo.get_plan(job_id)
    ver = plan_row["version"] if plan_row else 0
    if plan_row:
        plan = json.loads(plan_row["plan_json"])
        scenes = plan.get("scenes", [])
        if len(scenes) == n:
            plan["scenes"] = [{**scenes[old], "i": p} for p, old in enumerate(order)]
            ver = await repo.save_plan(job_id, json.dumps(plan, ensure_ascii=False), "manual:reorder", [])

    # 4. recompose (fonts+compose+lint) so captions/timing reflect the new order
    result = await recompose(repo, settings, job_id)
    return {"version": ver, "total_duration": timings.total, "order": order, **result}


async def retheme(repo: Repo, settings: Settings, job_id: str) -> dict:
    """Swap the plan's theme + brand in place (preserving manual scene edits) and
    recompose — instant palette re-skin without re-planning or re-rendering."""
    from ..themes import resolve as resolve_theme

    job = await repo.get_job(job_id)
    if not job:
        raise KeyError(job_id)
    plan_row = await repo.get_plan(job_id)
    if not plan_row:
        raise ValueError("no plan to retheme")
    config = json.loads(job["config_json"])
    plan = json.loads(plan_row["plan_json"])
    plan["theme"] = resolve_theme(settings, config).model_dump()
    plan.update(overlays_from_config(config))
    new_json = json.dumps(plan, ensure_ascii=False)
    ver = await repo.save_plan(job_id, new_json, "manual", [])
    result = await recompose(repo, settings, job_id)
    return {"version": ver, **result}


async def revoice(repo: Repo, settings: Settings, job_id: str, voice: str) -> dict:
    """Swap the narration voice for the WHOLE job. Text is unchanged, so the plan /
    keywords stay valid — we re-TTS every beat with the new voice, re-concat and
    re-time the narration track, bump the plan version (a cache-buster so the preview
    reloads), and recompose. config.lang is kept in lockstep with the voice (Kokoro
    derives the phonemizer from the voice prefix). Returns {version, total_duration, voice}."""
    from ..voices import is_known_voice, voice_lang

    if not is_known_voice(voice):
        raise ValueError(f"unknown voice {voice!r}")
    job = await repo.get_job(job_id)
    if not job:
        raise KeyError(job_id)
    segs = await repo.get_segments(job_id)
    if not segs:
        raise ValueError("no beats yet — run the job first")
    plan_row = await repo.get_plan(job_id)
    if not plan_row:
        raise ValueError("no plan to revoice")

    config = json.loads(job["config_json"])
    config["voice"] = voice
    config["lang"] = voice_lang(voice)
    speed = float(config.get("speed", 1.0))
    await repo.update_job(job_id, config_json=config)
    lang = config["lang"]

    ws = Workspace(settings.workspaces_dir / job_id).ensure()
    hf = HF(settings)

    # 1. re-TTS every beat with the new voice (wav paths stay put → concat just works)
    for s in segs:
        i = s["i"]
        linef = ws.tts / f"line_{i:03d}.txt"
        wav = ws.tts / f"seg_{i:03d}.wav"
        linef.write_text(s["text"], encoding="utf-8")
        payload = await hf.tts(str(linef), str(wav), voice=voice, lang=lang, speed=speed)
        dur = float(payload.get("durationSeconds") or await _ffprobe_duration(wav))
        await repo.db.execute(
            "UPDATE segments SET wav_path=?, wav_bytes=?, tts_duration=?, voice=?, lang=? WHERE job_id=? AND i=?",
            (str(wav), wav.stat().st_size, dur, voice, lang, job_id, i),
        )
    await repo.db.commit()

    # 2. re-concat the full narration + re-time every beat (running sum)
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
        raise RuntimeError(f"ffmpeg concat failed: {err.decode()[-300:]}")
    timings = Timings.from_durations([s["text"] for s in segs], [s["tts_duration"] for s in segs])
    (ws.ir / "timings.json").write_text(timings.model_dump_json(indent=2), encoding="utf-8")
    for sgm in timings.segments:
        await repo.db.execute("UPDATE segments SET start=?, end=? WHERE job_id=? AND i=?",
                              (sgm.start, sgm.end, job_id, sgm.i))
    await repo.db.commit()
    await repo.update_job(job_id, total_duration=timings.total)

    # 3. plan content is unchanged; re-save to bump the version so the preview reloads
    ver = await repo.save_plan(job_id, plan_row["plan_json"], "manual:revoice", [])

    # 4. recompose (fonts+compose+lint) so the narration audio + captions reflect the new voice
    result = await recompose(repo, settings, job_id)
    return {"version": ver, "total_duration": timings.total, "voice": voice, **result}


async def resynth_segment(repo: Repo, settings: Settings, job_id: str, i: int, new_text: str) -> dict:
    """Change one beat's narration text → re-TTS it → re-concat/re-time → re-derive
    its keyword → recompose. Returns {version, total_duration, beat_duration}."""
    job = await repo.get_job(job_id)
    if not job:
        raise KeyError(job_id)
    config = json.loads(job["config_json"])
    canvas = json.loads(job["canvas_json"])
    ws = Workspace(settings.workspaces_dir / job_id).ensure()
    hf = HF(settings)

    segs = await repo.get_segments(job_id)
    if not (0 <= i < len(segs)):
        raise IndexError(f"segment {i} out of range")
    new_text = new_text.strip()
    if not new_text:
        raise ValueError("narration text cannot be empty")

    # 1. re-TTS just this beat
    linef = ws.tts / f"line_{i:03d}.txt"
    wav = ws.tts / f"seg_{i:03d}.wav"
    linef.write_text(new_text, encoding="utf-8")
    payload = await hf.tts(str(linef), str(wav), voice=config.get("voice", DEFAULT_VOICE),
                           lang=config.get("lang", "zh"), speed=float(config.get("speed", 1.0)))
    dur = float(payload.get("durationSeconds") or await _ffprobe_duration(wav))
    await repo.db.execute(
        "UPDATE segments SET text=?, wav_path=?, wav_bytes=?, tts_duration=? WHERE job_id=? AND i=?",
        (new_text, str(wav), wav.stat().st_size, dur, job_id, i),
    )
    await repo.db.commit()

    # 2. re-concat the full narration + re-time every beat (running sum)
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
        raise RuntimeError(f"ffmpeg concat failed: {err.decode()[-300:]}")
    timings = Timings.from_durations([s["text"] for s in segs], [s["tts_duration"] for s in segs])
    (ws.ir / "timings.json").write_text(timings.model_dump_json(indent=2), encoding="utf-8")
    for sgm in timings.segments:
        await repo.db.execute("UPDATE segments SET start=?, end=? WHERE job_id=? AND i=?",
                              (sgm.start, sgm.end, job_id, sgm.i))
    await repo.db.commit()
    await repo.update_job(job_id, total_duration=timings.total)

    # 3. re-derive this scene's keyword (keep its kind), save a new plan version
    plan_row = await repo.get_plan(job_id)
    if plan_row:
        plan = json.loads(plan_row["plan_json"])
        scenes = plan.get("scenes", [])
        if 0 <= i < len(scenes):
            kw, clean = distill_keyword(new_text)
            slots = scenes[i].get("slots", {})
            kind = scenes[i]["kind"]
            # the slot the template actually reads for this kind's main text
            key = {"section": "title", "note": "body", "definition": "gloss",
                   "quote": "q", "stat": "label"}.get(kind, "headline")
            # Diagram kinds render extracted nodes, not a headline: re-distilling the
            # narration would write a slot nothing reads and re-add a caption that
            # just repeats the node labels.
            if kind not in DIAGRAM_KINDS:
                slots[key] = kw
                slots["verbatim"] = (not clean)
            scenes[i]["slots"] = slots
            scenes[i]["source"] = "rules:resynth"
        ver = await repo.save_plan(job_id, json.dumps(plan, ensure_ascii=False), "manual", [])
    else:
        ver = 0

    # 4. recompose (fonts+compose+lint) so captions/timing/keyword reflect the change
    result = await recompose(repo, settings, job_id)
    return {"version": ver, "total_duration": timings.total, "beat_duration": dur, **result}
