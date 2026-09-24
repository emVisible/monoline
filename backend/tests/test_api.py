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
        icons = c.get("/api/icons").json()["icons"]
        assert {"chart", "bolt", "sparkles"} <= set(icons)


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
