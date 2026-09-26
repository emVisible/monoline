"""API route smoke tests — cheap, no TTS/render. Guard the M3/V1–V5 endpoints'
request validation + not-found paths so a regression in routing/args is caught
without spinning the whole pipeline. Uses `with TestClient(app)` so the lifespan
starts the JobManager (routes under _manager need app.state.manager)."""
import os
import tempfile

os.environ["MONOLINE_APP_DIR"] = tempfile.mkdtemp(prefix="monoline-api-")

from fastapi.testclient import TestClient  # noqa: E402
from monoline.api.app import app  # noqa: E402

BOGUS = "000000000000000000000000"


def test_meta_endpoints():
    with TestClient(app) as c:
        themes = c.get("/api/themes").json()["themes"]
        assert any(t["id"] == "mono-ink" for t in themes)
        # V31a: /api/icons serves {name, body} so Studio can draw previews, not bare strings
        icons = c.get("/api/icons").json()["icons"]
        assert {"chart", "bolt", "sparkles"} <= {i["name"] for i in icons}
        assert all(i["body"].startswith("<") for i in icons)
        assert len(icons) >= 100


def test_script_status_shape():
    with TestClient(app) as c:
        r = c.get("/api/script/status")
        assert r.status_code == 200
        assert isinstance(r.json()["ready"], bool)


def test_create_job_validates_args():
    with TestClient(app) as c:
        # fps out of the 1..60 bound → pydantic 422 before anything runs
        assert c.post("/api/jobs", json={"script": "x", "fps": 999}).status_code == 422
        # empty script → 422
        assert c.post("/api/jobs", json={"script": ""}).status_code == 422


def test_missing_job_returns_404_on_all_new_routes():
    with TestClient(app) as c:
        assert c.get(f"/api/jobs/{BOGUS}/subtitles").status_code == 404
        assert c.get(f"/api/jobs/{BOGUS}/poster").status_code == 404
        assert c.post(f"/api/jobs/{BOGUS}/reorder", json={"order": [0]}).status_code == 404
        assert c.post(f"/api/jobs/{BOGUS}/plan/scenes/0/suggest").status_code == 404
        assert c.delete(f"/api/jobs/{BOGUS}/bgm").status_code == 404
        assert c.get(f"/api/jobs/{BOGUS}/subtitles?fmt=ass").status_code == 404


# --- V8 voice routes: cheap guards only (no TTS/synth in these paths) ---------
def test_voices_meta_lists_registry():
    with TestClient(app) as c:
        d = c.get("/api/voices").json()
        assert d["default"] == "zf_xiaoxiao"
        ids = [v["id"] for v in d["voices"]]
        assert "af_heart" in ids and "zf_xiaobei" in ids and len(ids) == 25
        assert sum(1 for v in d["voices"] if v["lang"] == "zh") == 8   # Chinese is well-covered
        assert all({"id", "label", "lang", "group"} <= set(v) for v in d["voices"])


def test_voice_sample_rejects_unknown_without_synth():
    with TestClient(app) as c:
        assert c.get("/api/voices/bogus_999/sample").status_code == 422


def test_create_job_rejects_unknown_voice_before_queueing():
    with TestClient(app) as c:
        # unknown voice → 422 at the route guard, never reaches enqueue/pipeline
        r = c.post("/api/jobs", json={"script": "hello.", "voice": "not_a_voice"})
        assert r.status_code == 422


def test_change_voice_guards_missing_job_and_unknown_voice():
    with TestClient(app) as c:
        # unknown voice is caught first (before the job lookup) → 422
        assert c.post(f"/api/jobs/{BOGUS}/voice", json={"voice": "bogus"}).status_code == 422
        # a real voice on a nonexistent job → KeyError → 404
        assert c.post(f"/api/jobs/{BOGUS}/voice", json={"voice": "af_heart"}).status_code == 404


# ---------- V47b: the beat count has one owner ----------

LONG_CLAUSE_SENTENCE = (
    "这项技术改变了整个行业，它降低了成本，也提升了速度，"
    "同时让团队能够专注于创造而不是重复劳动，最终形成了一套完整的方法论。")
# 1300 lines of ≥6-char sentences → 1300 beats, i.e. past the 1200 ceiling by 100.
OVER_CAP_SCRIPT = "\n".join(f"第{i}条要点说明文字，包含两个从句。" for i in range(1300))


def test_script_preview_agrees_with_the_segmenter():
    """The UI shows this number as the length of the video about to be made. It used to be a
    local regex that counted one beat here; the pipeline makes two, because only Python
    splits an over-long sentence at its clauses."""
    from monoline.pipeline.segment import HARD_CAP, SECONDS_PER_BEAT, segment_text

    with TestClient(app) as c:
        d = c.post("/api/script/preview", json={"script": LONG_CLAUSE_SENTENCE}).json()
        assert d["beats"] == len(segment_text(LONG_CLAUSE_SENTENCE))
        assert d["beats"] > 1, "preview must not regress to the old one-line-one-beat count"
        assert d["seconds"] == round(d["beats"] * SECONDS_PER_BEAT)
        assert d["cap"] == HARD_CAP and d["over_cap"] is False
        # an over-cap paste is reported, not rejected: the number IS the warning
        over = c.post("/api/script/preview", json={"script": OVER_CAP_SCRIPT}).json()
        assert over["beats"] == 1300 and over["over_cap"] is True
        assert c.post("/api/script/preview", json={"script": "   \n  "}).json()["beats"] == 0


def test_create_job_refuses_an_over_cap_script_at_intake():
    """Assemble raises the same ValueError minutes later, after the job exists and TTS has
    synthesised every beat of a script that can never render. 422 here, before the queue."""
    with TestClient(app) as c:
        r = c.post("/api/jobs", json={"script": OVER_CAP_SCRIPT})
        assert r.status_code == 422
        assert "hard cap" in r.json()["detail"]
        # a created job answers with an id; refusing means no row was ever written
        assert "job_id" not in r.json()


def test_the_outline_is_reviewable_and_editable_before_any_audio():
    """H5: the cut steers everything downstream, so it has to be seen and fixed BEFORE the run.
    `POST /outline` segments + storyboards without touching TTS; `PATCH` makes the user's list
    the job — and claims the script/plan stages, because a later run that re-cut the source
    would silently undo every merge and deletion (measured: it did, before the claim existed)."""
    script = "## 开场\n\n深海里的生物大多能自己发光。\n\n## 机制\n\n荧光素酶催化了这一步。\n\n- 蓝光穿透最远\n- 绿光被水吸收\n"
    with TestClient(app) as c:
        jid = c.post("/api/jobs", json={"script": script, "llm_plan": False}).json()["job_id"]
        out = c.post(f"/api/jobs/{jid}/outline").json()
        kinds = [e["kind"] for e in out["entries"]]
        assert out["beats"] == len(out["entries"]) >= 5, out
        assert "开场" in [e["text"] for e in out["entries"]]
        assert out["sections"] == ["开场", "机制"], out["sections"]
        assert all(e["seconds"] > 0 for e in out["entries"])
        assert kinds[0] == "section", "标题必须先是分节页，大纲才有骨架"
        # nothing ran yet: no audio, no render
        stages = {s["key"]: s["status"] for s in c.get(f"/api/jobs/{jid}").json()["stages"]}
        assert "tts" not in stages or stages["tts"] != "succeeded", stages

        # the user merges two beats, deletes one, and pins a divider on another
        edits = [dict(e) for e in out["entries"]]
        edits = [e for e in edits if not e["text"].startswith("蓝光")]
        for e in edits:
            if e["text"] == "荧光素酶催化了这一步。":
                e["text"] = "荧光素酶催化了这一步，绿光被水吸收。"
        after = c.patch(f"/api/jobs/{jid}/outline", json={"entries": edits}).json()
        assert after["beats"] == len(edits), after
        assert any("绿光被水吸收" in e["text"] for e in after["entries"])
        assert not any(e["text"].startswith("蓝光") for e in after["entries"])
        assert after["version"] > 1, "大纲落成了新的 plan 版本"

        # and the run that follows starts at tts, not at the cut
        stages = {s["key"]: s["status"] for s in c.get(f"/api/jobs/{jid}").json()["stages"]}
        assert stages.get("script") == "succeeded" and stages.get("plan") == "succeeded", stages
        assert c.get(f"/api/jobs/{jid}/outline").json()["beats"] == after["beats"]
        assert c.patch(f"/api/jobs/{jid}/outline", json={"entries": []}).status_code == 422


def test_the_outline_is_where_the_two_unreachable_kinds_get_triggered():
    """H3's audit: of 28 kinds, `image` and `showcase` are the two no rule can ever reach —
    a sentence never admits it is describing a picture. The storyboard is the only honest
    trigger, so the outline has to carry the asset with the beat. The path is validated
    against the shape `POST /assets` mints, because this string reaches an <img src>."""
    import hashlib

    script = "深海里的生物大多能自己发光。\n\n这不是反射阳光，而是一场发生在体内的化学反应。\n"
    png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000a49444154789c6300010000050001"
                        "0d0a2db40000000049454e44ae426082")
    rel = f"assets/{hashlib.sha1(png).hexdigest()[:16]}.png"
    with TestClient(app) as c:
        jid = c.post("/api/jobs", json={"script": script, "llm_plan": False}).json()["job_id"]
        out = c.post(f"/api/jobs/{jid}/outline").json()
        assert all(e["image"] == "" for e in out["entries"])
        up = c.post(f"/api/jobs/{jid}/assets", files={"file": ("shot.png", png, "image/png")})
        assert up.status_code == 200 and up.json()["rel"] == rel, up.text

        edits = [dict(e) for e in out["entries"]]
        edits[0]["kind"] = "image"
        edits[0]["image"] = rel
        after = c.patch(f"/api/jobs/{jid}/outline", json={"entries": edits}).json()
        assert after["imaged"] == 1, after
        assert after["entries"][0]["kind"] == "image" and after["entries"][0]["image"] == rel

        # the picture has to survive into the storyboard the render reads
        plan = c.get(f"/api/jobs/{jid}").json()["plan"]["scenes"][0]
        assert plan["kind"] == "image" and plan["slots"]["image"] == rel, plan

        bad = [dict(e) for e in out["entries"]]
        bad[1]["kind"], bad[1]["image"] = "image", "../../etc/passwd"
        assert c.patch(f"/api/jobs/{jid}/outline", json={"entries": bad}).status_code == 422
        ghost = [dict(e) for e in out["entries"]]
        ghost[1]["kind"], ghost[1]["image"] = "image", f"assets/{'0' * 16}.png"
        assert c.patch(f"/api/jobs/{jid}/outline", json={"entries": ghost}).status_code == 422
