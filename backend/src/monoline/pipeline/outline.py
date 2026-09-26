"""The outline — the whole film as one editable list, BEFORE any audio is paid for.

Why this exists: the pipeline used to run end-to-end on the first 运行, so the first moment a
user could see 「这片子被切成了什么」 was after TTS, composition and a render. The cut is the
decision that steers everything downstream (a beat split in the wrong place cannot be repaired
by choosing a different layout), so it has to be reviewable first.

`build()` is the read side: segment + storyboard, no audio. `apply()` is the write side: the
user's list becomes the segments and the plan, stored with `source="manual"` so the run that
follows keeps it instead of re-deriving it from the rules.

Kind pinning is deliberately limited to the kinds that can be painted from a beat's own words.
A chart kind needs rows the beat may not contain, and inventing them would put numbers on
screen that the script never said — that choice stays in Studio, where the slots are editable.
"""
from __future__ import annotations

import json
import re

from ..ir.sceneplan import KINDS, Canvas, ScenePlan, overlays_from_config
from .planner import RulePlanner, apply_icons, number_sections
from .rotation import label_sections
from .segment import HARD_CAP, segment_text

# Every one of these templates falls back to `seg.text` when its slot is empty, so pinning one
# can never paint a hole.
_TEXT_KINDS = {"title", "statement", "section", "definition", "quote", "note", "summary",
               "split", "poster"}
# Rough Mandarin rate, measured off this project's own narration: ~4.3 chars/second plus a
# breath per beat. Good enough to plan a film with; the real number arrives with the TTS.
_CHARS_PER_SECOND = 4.3
_BREATH = 0.45


def estimate(text: str) -> float:
    n = len(re.sub(r"\s", "", str(text or "")))
    return round(max(1.2, n / _CHARS_PER_SECOND + _BREATH), 2)


def storyboard(beats: list[str], *, script: str, brand: str) -> list[dict]:
    """The rule storyboard for a list of beats — the same call the `plan` stage makes."""
    scenes = RulePlanner().plan(beats, brand=brand, script=script)
    apply_icons(scenes, beats)
    number_sections(scenes)
    return scenes


def _entries(segs: list[dict], scenes: list[dict]) -> list[dict]:
    labels = label_sections([dict(s) for s in scenes])
    out = []
    for i, seg in enumerate(segs):
        sc = scenes[i] if i < len(scenes) else {}
        label = labels[i].get("section", "") if i < len(labels) else ""
        slots = sc.get("slots") or {}
        pics = ([slots["image"]] if slots.get("image") else
                [r.get("img", "") for r in slots.get("rows") or []
                 if isinstance(r, dict) and r.get("img")])
        out.append({"i": i, "text": seg["text"], "kind": sc.get("kind", "statement"),
                    "source": sc.get("source", ""), "section": label,
                    "image": pics[0] if pics else "", "images": pics,
                    "seconds": estimate(seg["text"])})
    return out


def _view(entries: list[dict]) -> dict:
    return {"entries": entries, "beats": len(entries),
            "est_seconds": round(sum(e["seconds"] for e in entries), 1),
            "sections": sorted({e["section"] for e in entries if e["section"]})}


async def store(repo, settings, job_id: str, config: dict, scenes: list[dict], *, source: str) -> int:
    """Save the storyboard AND claim the two stages it replaces.

    The outline is the approved cut: without the stage rows the next run's `script` stage would
    re-segment the source and quietly undo every merge, split and deletion the user just made.
    The hashes are the pipeline's own, so a later real edit to `script_text` still invalidates
    them and re-cuts.
    """
    from ..db.repo import now_iso
    from ..themes import resolve as resolve_theme
    from .runner import _h
    from .workspace import Workspace

    job = await repo.get_job(job_id)
    canvas = Canvas(**json.loads((job or {}).get("canvas_json") or "{}"))
    plan = ScenePlan(canvas=canvas, theme=resolve_theme(settings, config).model_dump(),
                     scenes=scenes, **overlays_from_config(config))
    js = plan.model_dump_json()
    version = await repo.save_plan(job_id, js, source, [])

    script = (job or {}).get("script_text") or ""
    ws = Workspace(settings.workspaces_dir / job_id).ensure()
    (ws.ir / "scene_plan.json").write_text(js, encoding="utf-8")
    await repo.upsert_stage(job_id, "script", 0, status="succeeded",
                            finished_at=now_iso(), input_hash=_h(script))
    await repo.upsert_stage(job_id, "plan", 3, status="succeeded", finished_at=now_iso(),
                            input_hash=_h(script, config.get("brand"), config.get("theme"),
                                             config.get("accent")))
    return version


async def build(repo, settings, job_id: str) -> dict:
    """Segment + storyboard the job (no audio), persist both, return the outline."""
    job = await repo.get_job(job_id)
    if not job:
        raise KeyError(job_id)
    config = json.loads(job["config_json"])
    script = job["script_text"] or ""
    beats = segment_text(script)
    if not beats:
        raise ValueError("script is empty")
    if len(beats) > HARD_CAP:
        raise ValueError(f"{len(beats)} beats exceeds the cap {HARD_CAP}")

    await repo.replace_segments(job_id, [{"i": i, "text": t, "line_no": i + 1}
                                         for i, t in enumerate(beats)])
    scenes = storyboard(beats, script=script, brand=config.get("brand", "Monoline"))
    await store(repo, settings, job_id, config, scenes, source="rules")
    return _view(_entries(await repo.get_segments(job_id), scenes))


async def current(repo, settings, job_id: str) -> dict:
    """The outline as it stands now, from whatever is already stored — no re-segmenting."""
    job = await repo.get_job(job_id)
    if not job:
        raise KeyError(job_id)
    segs = await repo.get_segments(job_id)
    row = await repo.get_plan(job_id)
    scenes = json.loads(row["plan_json"]).get("scenes", []) if row else []
    if len(scenes) != len(segs):
        config = json.loads(job["config_json"])
        scenes = storyboard([s["text"] for s in segs], script=job["script_text"] or "",
                            brand=config.get("brand", "Monoline"))
    return _view(_entries(segs, scenes))


# The asset path a beat may be pointed at. `POST /assets` mints exactly this shape
# (`assets/<sha1-16>.<ext>`), so anything else — including a traversal — is refused.
_ASSET = re.compile(r"^assets/[0-9a-f]{16}\.(?:png|jpe?g|webp|gif)$")


async def apply(repo, settings, job_id: str, edits: list[dict]) -> dict:
    """Take the user's list — their order, their text — and make it the job.

    Deletion is absence from the list; merge and split are edits of two rows; reorder is the
    order. The narration is re-cut from these strings on the next run, which is the point.
    """
    job = await repo.get_job(job_id)
    if not job:
        raise KeyError(job_id)
    config = json.loads(job["config_json"])

    beats: list[str] = []
    wanted: list[tuple[str, str]] = []
    for e in edits:
        text = re.sub(r"\s+", " ", str(e.get("text") or "")).strip()
        if not text:
            continue
        beats.append(text)
        # `images` wins when it carries anything; the singular `image` is what a one-picture
        # beat sends. An empty `images: []` must not shadow it — that is how a pinned `image`
        # beat silently stayed a statement.
        pics = [str(x) for x in (e.get("images") or ([str(e["image"])] if e.get("image") else []))]
        wanted.append((str(e.get("kind") or ""), pics))
    if not beats:
        raise ValueError("大纲是空的：至少留一拍")
    if len(beats) > HARD_CAP:
        raise ValueError(f"{len(beats)} beats exceeds the cap {HARD_CAP}")

    await repo.replace_segments(job_id, [{"i": i, "text": t, "line_no": i + 1}
                                         for i, t in enumerate(beats)])
    scenes = storyboard(beats, script=job["script_text"] or "",
                        brand=config.get("brand", "Monoline"))
    from ..pipeline.workspace import Workspace

    comp = Workspace(settings.workspaces_dir / job_id).composition

    def checked(img: str) -> str:
        # this string ends up in an <img src>, so only the shape `POST /assets` mints passes
        if not _ASSET.match(img) or not (comp / img).exists():
            raise ValueError(f"这一拍的图片不可用：{img[:40]}")
        return img

    pinned = images = 0
    for sc, (want, pics) in zip(scenes, wanted):
        slots = sc.setdefault("slots", {})
        if want == "image" and pics:
            # `image` and `showcase` are the two kinds no rule can ever reach (审计 H3): a
            # picture is not something a sentence admits to. This is their trigger.
            slots["image"] = checked(pics[0])
            slots["verbatim"] = True
            sc["kind"], sc["source"] = "image", "manual:outline"
            images += 1
        elif want == "showcase" and pics:
            if len(pics) < 2:
                raise ValueError("组图至少要两张图；只有一张请用「图」这一类")
            slots["rows"] = [{"img": checked(p), "k": "", "v": ""} for p in pics[:4]]
            slots["verbatim"] = True
            sc["kind"], sc["source"] = "showcase", "manual:outline"
            images += 1
        elif want and want in KINDS and want != sc["kind"] and want in _TEXT_KINDS:
            sc["kind"] = want
            sc["source"] = "manual:outline"
            pinned += 1
    version = await store(repo, settings, job_id, config, scenes, source="manual")
    return {**_view(_entries(await repo.get_segments(job_id), scenes)),
            "pinned": pinned, "imaged": images, "version": version}
