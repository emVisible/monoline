"""Smoke tests — no render, no network. Assert the M0 contract shape + key logic."""
import os
import tempfile

# Isolate app data before importing settings (lru_cache reads env at call time).
os.environ["MONOLINE_APP_DIR"] = tempfile.mkdtemp(prefix="monoline-test-")

from fastapi.testclient import TestClient  # noqa: E402
from monoline.api.app import app  # noqa: E402


def test_health_shape():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.json()
    assert d["app"] == "monoline"
    assert "ok" in d and isinstance(d["checks"], list)
    names = {c["name"] for c in d["checks"]}
    assert {"node", "ffmpeg", "gsap_vendored", "ofl_cjk_font"} <= names


def test_doctor_reports_node_and_ffmpeg():
    from monoline.doctor import run_doctor
    doc = run_doctor(probe_sidecar=False)
    by = {c["name"]: c["state"] for c in doc["checks"]}
    assert by["node"] in {"ok", "wrong_version", "missing"}
    assert by["ffmpeg"] in {"ok", "missing"}


def test_segmenter_splits_single_line_into_beats():
    from monoline.pipeline.segment import segment_text
    beats = segment_text("这是一句完整的话。这是第二句完整的话。这是第三句话，里面有一个很长的从句，需要被拆开成两拍。")
    assert len(beats) >= 3
    assert all(len(b) <= 60 for b in beats)


def test_segmenter_keeps_semicolon_kv_line_intact():
    # regression: ； is a clause boundary, not sentence-final — splitting there used
    # to shred "命中：68.8%；覆盖：42%…" into single-number stat fragments instead of a table.
    from monoline.pipeline.segment import segment_text
    from monoline.pipeline.planner import RulePlanner
    line = "命中：68.8%；覆盖：42%；准确：91%。"
    assert segment_text(line) == [line]          # one beat, not three
    # classify as a non-first beat (index 0 would be forced to title by plan())
    scene = RulePlanner()._classify(1, line)
    assert scene["kind"] == "table"
    assert [r["k"] for r in scene["slots"]["rows"]] == ["命中", "覆盖", "准确"]


def test_planner_classifies_content():
    from monoline.pipeline.planner import RulePlanner
    scenes = RulePlanner().plan(["标题句。", "它在基准上拿到 68.8%。", "需要注意，以官方为准。"])
    kinds = [s["kind"] for s in scenes]
    assert kinds[0] == "title"
    assert kinds[-1] == "summary" or "note" in kinds
    assert "stat" in kinds  # 68.8% → stat


def test_distill_skips_leading_connectives():
    from monoline.pipeline.planner import distill_keyword
    assert distill_keyword("总之，深海是一个发光的世界。")[0] == "深海是一个发光的世界"
    assert distill_keyword("首先，我们要明确目标。")[0] == "我们要明确目标"
    # a normal first clause is untouched
    assert distill_keyword("深海发光：一个被低估的现象。")[0] == "深海发光"
    # a short leading setup clause ("相比旧版，…") is skipped for the real point
    assert distill_keyword("相比旧版，Pro 版更适合大型团队。")[0] == "Pro 版更适合大型团队"
    assert distill_keyword("对于新用户，我们提供专属引导。")[0] == "我们提供专属引导"
    # short temporal lead-ins too ("那晚之后", "起初", "三年以后")
    assert distill_keyword("那晚之后，他决定离开这座城市。")[0] == "他决定离开这座城市"
    assert distill_keyword("起初，他并不知情。")[0] == "他并不知情"


def test_note_and_quote_suppress_duplicate_caption():
    from monoline.pipeline.planner import RulePlanner
    from monoline.compose.icons import KIND_ICON
    note = RulePlanner()._classify(1, "需要注意，具体以官方为准。")
    assert note["kind"] == "note" and note["slots"]["verbatim"] is True   # body == full sentence → hide caption
    assert KIND_ICON["note"] == ""                                        # the "!" marker is the note's identity, no info icon
    quote = RulePlanner()._classify(1, "「用户第一，其余其次。」")
    assert quote["kind"] == "quote" and quote["slots"]["verbatim"] is True


def test_compose_title_adaptive_size_no_overflow():
    import json
    import re
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition
    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    long_headline = "2026年9月23日，OpenAI 发布 GPT-6 系列两款模型：Sol 和 Luna"
    t = Timings.from_durations([long_headline, "第二拍"], [4.0, 3.0])
    plan = ScenePlan(theme=theme, scenes=[
        {"i": 0, "kind": "title", "slots": {"headline": long_headline}},
        {"i": 1, "kind": "statement", "slots": {"headline": "第二拍"}}])
    html = render_composition(t, plan)
    m = re.search(r"k-title.*?font-size:calc\((\d+)px", html, re.S)
    assert m and int(m.group(1)) < 190


def test_reconcile_resumes_orphaned_jobs():
    import asyncio
    import tempfile
    from pathlib import Path
    from monoline.settings import Settings
    from monoline.queue.manager import JobManager

    async def run():
        s = Settings()
        s.app_dir = Path(tempfile.mkdtemp(prefix="monoline-recon-"))
        s.ensure_dirs()
        m = JobManager(s)
        await m.repo.connect()
        stuck = await m.repo.create_job(script_text="x", config={}, canvas={}, title="t", slug="t")
        await m.repo.update_job(stuck, status="running")
        done = await m.repo.create_job(script_text="y", config={}, canvas={}, title="u", slug="u")
        await m.repo.update_job(done, status="succeeded")
        resumed = await m.reconcile()
        assert resumed == [stuck]
        assert (await m.repo.get_job(stuck))["status"] == "queued"
        assert m._queue.qsize() == 1
        evs = await m.repo.get_events_since(stuck, 0)
        assert any(e["kind"] == "reconcile" for e in evs)
        await m.repo.close()

    asyncio.run(run())


def test_llm_prompt_build_and_clean():
    from monoline.llm.client import build_messages, _clean
    msgs = build_messages("深海发光", tone="punchy", length="short", lang="zh")
    assert len(msgs) == 2 and msgs[1]["content"] == "深海发光"
    assert "6-8" in msgs[0]["content"]
    cleaned = _clean("1. 第一拍\n- 第二拍\n**第三拍**\n\n")
    assert cleaned.splitlines() == ["第一拍", "第二拍", "第三拍"]


def test_llm_not_configured_raises():
    import asyncio
    from monoline.settings import Settings
    from monoline.llm.client import generate_script, LLMNotConfigured

    async def run():
        s = Settings()
        s.llm_api_key = ""
        s.llm_base_url = "https://api.openai.com/v1"
        assert s.llm_ready is False
        try:
            await generate_script(s, "x")
            raise AssertionError("expected LLMNotConfigured")
        except LLMNotConfigured:
            pass

    asyncio.run(run())


def test_sidecar_render_signals_fallback_when_unreachable():
    import asyncio
    from monoline.settings import Settings
    from monoline.hf.cli import HF, SidecarUnavailableError

    async def run():
        s = Settings()
        s.sidecar_port = 1  # nothing listens → connect error → caller falls back to CLI
        hf = HF(s)
        try:
            await hf.render_via_sidecar("/tmp", "/tmp/nope.mp4", fps=24, quality="draft", timeout=5)
            raise AssertionError("expected SidecarUnavailableError")
        except SidecarUnavailableError:
            pass

    asyncio.run(run())


def test_icons_planner_assign_and_whitelist():
    from monoline.pipeline.planner import RulePlanner
    from monoline.compose.icons import svg, names
    scenes = RulePlanner().plan(["开场。", "效率高达 68.8%。", "先看三点。", "收尾。"])
    by_kind = {s["kind"]: s["slots"].get("icon") for s in scenes}
    assert by_kind.get("stat") == "chart"
    assert by_kind.get("section") == "arrow"
    assert "<svg" in svg("chart") and svg("nope") == ""
    assert "bolt" in names()


def test_themes_resolve_accent_and_fallback():
    from monoline.settings import Settings
    from monoline.themes import resolve, available
    s = Settings()
    ids = {t["id"] for t in available(s)}
    assert {"mono-ink", "mono-paper"} <= ids and "ui" not in ids   # ui.json is not a theme
    base = resolve(s, {})
    assert base.id == "mono-ink" and base.color.get("accent")
    bright = resolve(s, {"accent": "#C4F82A"})                       # light accent → dark ink for contrast
    assert bright.color["accent"] == "#C4F82A" and bright.color["accent_ink"] == "#0B0B0C"
    dark = resolve(s, {"accent": "#20304A"})                          # dark accent → white ink
    assert dark.color["accent_ink"] == "#FFFFFF"
    assert resolve(s, {"theme": "does-not-exist"}).id == "mono-ink"  # unknown → default


def test_viz_pct_and_ring():
    from monoline.compose.viz import pct, ring
    assert pct("68.8%") == 68.8
    assert pct("0.42") == 42.0
    assert pct("0.001") is None          # tiny decimal (learning rate) → number, not a 0.1% ring
    assert pct("1200") is None          # bare count → no guess
    assert pct("很高") is None
    r = ring(25.0)
    assert "<svg" in r and "stroke-dashoffset" in r and "263.894" in r


def test_viz_row_bars():
    from monoline.compose.viz import row_bars
    assert row_bars(["68.8%", "42%", "91%"]) == [68.8, 42.0, 91.0]      # percentages pass through
    assert row_bars(["120", "45", "30"]) == [100.0, 37.5, 25.0]          # bare numbers → relative to max
    assert row_bars(["68.8%", "120"]) == [None, None]                    # mixed → no bars
    assert row_bars(["高", "低"]) == [None, None]                        # non-numeric → no bars
    assert row_bars(["120"]) == [None]                                   # single row → nothing to compare
    assert row_bars([]) == []


def test_image_kind_and_inset_image_render():
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme, KINDS
    from monoline.compose.engine import render_composition
    assert "image" in KINDS
    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    t = Timings.from_durations(["配图。", "纯图卡"], [3.0, 3.0])
    plan = ScenePlan(theme=theme, scenes=[
        {"i": 0, "kind": "statement", "slots": {"headline": "配图", "image": "assets/a.png"}},
        {"i": 1, "kind": "image", "slots": {"image": "assets/b.jpg", "headline": "纯图卡"}}])
    html = render_composition(t, plan)
    assert '<img src="assets/a.png"' in html          # inset 配图 on a text kind
    assert '<img class="full" src="assets/b.jpg"' in html  # dedicated image kind
    # image kind must NOT also emit the generic scene-media block — count actual emitted
    # blocks (class="scene-media"), not the bare token, which also appears in CSS + the
    # stagger JS selector. Only scene-0 (statement w/ image) emits one; the image kind emits zero.
    assert html.count('class="scene-media"') == 1


def test_list_template_renders_items():
    # regression: `scene.slots.items` hit the dict's .items METHOD (Jinja attr-first),
    # crashing compose for every 、-list. Must use subscript slots['items'].
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition
    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    t = Timings.from_durations(["列表。"], [2.0])
    plan = ScenePlan(theme=theme, scenes=[
        {"i": 0, "kind": "list", "slots": {"title": "三种", "items": ["发光", "反射", "散射"]}}])
    html = render_composition(t, plan)
    assert html.count('<li class="item"') == 3
    assert "发光" in html and "散射" in html


def test_subtitles_srt_vtt_formatting():
    from monoline.pipeline.subtitles import to_srt, to_vtt
    segs = [
        {"i": 0, "start": 0.0, "end": 2.5, "text": "第一句。"},
        {"i": 1, "start": 2.5, "end": 6.0, "text": "  第二句  "},
        {"i": 2, "start": 6.0, "end": 6.0, "text": ""},   # empty → skipped
    ]
    srt = to_srt(segs)
    assert srt.startswith("1\n00:00:00,000 --> 00:00:02,500\n第一句。")
    assert "2\n00:00:02,500 --> 00:00:06,000\n第二句" in srt
    assert "第三" not in srt and srt.count("-->") == 2      # empty cue dropped, indices renumbered
    vtt = to_vtt(segs)
    assert vtt.startswith("WEBVTT\n")
    assert "00:00:02.500 --> 00:00:06.000" in vtt          # dot separator in VTT
    assert to_srt([]) == "" and to_vtt([]).startswith("WEBVTT")



# --- V8 voice registry -------------------------------------------------------
def test_voice_registry_shape():
    from monoline.voices import DEFAULT_VOICE, VOICES, available
    assert available() == [dict(v) for v in VOICES]         # same order, defensive copy
    ids = [v["id"] for v in VOICES]
    assert len(ids) == len(set(ids)) == 25
    assert DEFAULT_VOICE in ids
    assert sum(1 for v in VOICES if v["lang"] == "zh") == 8   # 8 Chinese voices
    for v in VOICES:
        assert set(v) >= {"id", "label", "lang", "group", "gender"}
        assert v["gender"] in {"m", "f"}
    # every voice's id-prefix letter must agree with its declared lang (Kokoro
    # auto-detects phonemizer from the prefix; drift here = silent mispronounce)
    prefix_lang = {"a": "en-us", "b": "en-gb", "e": "es", "f": "fr-fr", "j": "ja", "z": "zh"}
    for v in VOICES:
        assert prefix_lang[v["id"][0]] == v["lang"], v


def test_voice_lookup_helpers():
    from monoline.voices import is_known_voice, sample_text, voice_lang
    assert is_known_voice("af_heart") and is_known_voice("zf_xiaobei")
    assert not is_known_voice("nope") and not is_known_voice("") and not is_known_voice(None)
    assert voice_lang("jf_alpha") == "ja" and voice_lang("bogus") is None
    # a sample line exists for every advertised language, non-empty, matches the voice
    for v in [  {"id": "zf_xiaobei"} ]:
        assert sample_text(v["id"]).strip()
    assert sample_text("af_heart") == sample_text("am_adam")   # both en-us share a line


def test_pick_icon_semantic():
    from monoline.compose.icons import _ICONS, pick_icon
    assert pick_icon("营收增长了 30%") == "chart"
    assert pick_icon("速度提升到毫秒级") == "bolt"
    assert pick_icon("这是一个模型架构") == "cpu"
    assert pick_icon("需要注意口径") == "info"
    assert pick_icon("完全无关的普通句子啊") == ""
    # every mapped icon must exist in the library (no typos → silent blank)
    from monoline.compose.icons import _ICON_KEYWORDS
    for icon, _ in _ICON_KEYWORDS:
        assert icon in _ICONS, icon


def test_layout_presets_render_distinct_and_validate():
    import json
    import re
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition
    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    t = Timings.from_durations(["第一拍。", "第二拍"], [3.0, 3.0])
    plan = ScenePlan(theme=theme, scenes=[
        {"i": 0, "kind": "statement", "slots": {"headline": "第一拍"}},
        {"i": 1, "kind": "stat", "slots": {"value": "30", "label": "第二拍"}}])
    # the stylesheet ships all three preset blocks; the <body data-layout> attr is what
    # selects one, so read the value off the body tag rather than substring-matching CSS.
    def body_layout(html):
        return re.search(r"<body[^>]*\bdata-layout=\"(\w+)\"", html).group(1)
    assert body_layout(render_composition(t, plan)) == "minimal"           # default
    assert body_layout(render_composition(t, plan, layout="editorial")) == "editorial"
    assert body_layout(render_composition(t, plan, layout="bold")) == "bold"
    # both preset rule blocks are present in every render (they only activate via the attr)
    minimal = render_composition(t, plan, layout="minimal")
    assert 'data-layout="editorial"] .frame' in minimal and 'data-layout="bold"] .eyebrow' in minimal
    # unknown layout fails closed to minimal (never an empty/invalid attribute)
    assert body_layout(render_composition(t, plan, layout="comic-sans")) == "minimal"


def test_count_up_parsing_contract():
    import json
    from pathlib import Path
    from monoline.compose.engine import _env
    cu = _env().globals["count_up"]
    # clean numeric cores split into prefix + number + suffix (suffix carries the unit)
    assert cu("92%") == {"prefix": "", "num": "92", "dec": 0, "suffix": "%"}
    assert cu("1.5万") == {"prefix": "", "num": "1.5", "dec": 1, "suffix": "万"}
    assert cu("约 30％") == {"prefix": "约 ", "num": "30", "dec": 0, "suffix": "％"}
    assert cu("↓3倍") == {"prefix": "↓", "num": "3", "dec": 0, "suffix": "倍"}
    assert cu("0.001")["dec"] == 3
    # anything with digits in the "suffix" (thousands sep, multi-number, dates) → static fallback
    assert cu("1,000") is None
    assert cu("2026年9月") is None
    assert cu("九十二") is None
    assert cu("") is None
