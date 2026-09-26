"""Smoke tests — no render, no network. Assert the M0 contract shape + key logic."""
import os
import pathlib
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
    assert scene["kind"] == "bars"          # three comparable rates → compared by length (V31d)
    assert [r["k"] for r in scene["slots"]["rows"]] == ["命中", "覆盖", "准确"]


def test_segmenter_strips_list_markers():
    # V18: pasted markdown/numbered bullets must not leak their marker into the
    # headline/caption/TTS, and "2. x" must not misfire as a stat on the "2".
    from monoline.pipeline.segment import segment_text
    from monoline.pipeline.planner import RulePlanner
    beats = segment_text("- 快速启动整套部署流程\n• 稳定支撑每秒十万并发\n2. 显著降低运维成本")
    assert beats == ["快速启动整套部署流程", "稳定支撑每秒十万并发", "显著降低运维成本"]
    # the numbered item is a statement, not a stat keyed off the "2"
    assert RulePlanner()._classify(1, beats[2])["kind"] != "stat"
    # decimals and negatives are NOT list markers — left intact
    assert segment_text("学习率 3.14 是基准值") == ["学习率 3.14 是基准值"]
    assert segment_text("-10% 是可接受的误差") == ["-10% 是可接受的误差"]
    # V20: markdown headers "# " stripped; "C#" (mid-line) and "#hashtag" (no space) untouched
    assert segment_text("# 深海发光概览与要点") == ["深海发光概览与要点"]
    assert segment_text("用 C# 写的高性能服务") == ["用 C# 写的高性能服务"]
    assert segment_text("#hashtag 话题很火") == ["#hashtag 话题很火"]


def test_segmenter_keeps_short_list_items_separate():
    # V21: stripping a marker can drop an item under min_chars; explicit list/header lines
    # must still stay their own beat (not merge into a run-on), while ordinary short
    # fragments still fold into their neighbour.
    from monoline.pipeline.segment import segment_text
    assert segment_text("步骤如下。\n1. 设计系统\n2. 构建模型\n3. 上线服务") == \
        ["步骤如下。", "设计系统", "构建模型", "上线服务"]
    assert segment_text("# 标题\n- 第一点\n- 第二点") == ["标题", "第一点", "第二点"]
    # unprotected tiny fragment still merges
    assert segment_text("这是短句。这是另一句完整的话在这里。") == ["这是短句。这是另一句完整的话在这里。"]


def test_segmenter_strips_markdown_inline():
    # V23: pasted markdown (**bold**, [text](url), `code`, *em*) must not leak markup.
    from monoline.pipeline.segment import segment_text
    assert segment_text("这是**重点**内容") == ["这是重点内容"]
    assert segment_text("详见 [官方文档](https://x.com/d) 了解。") == ["详见 官方文档 了解。"]
    assert segment_text("运行 `npm install` 即可") == ["运行 npm install 即可"]
    # a lone asterisk between spaces (multiplication) is NOT emphasis → preserved
    assert segment_text("2 * 3 = 6 这个公式") == ["2 * 3 = 6 这个公式"]


def test_assert_determinism_allows_text_urls_blocks_remote_resources():
    # V22: a URL in pasted display text must NOT fail the job (it's autoescaped, inert);
    # only remote RESOURCE references are forbidden.
    from monoline.compose.assert_determinism import assert_determinism, CompositionAssertionError
    assert_determinism('<div class="inner">see https://example.com/docs</div>')  # no raise
    for bad in ('<img src="https://evil/x.png" id=i>',
                '<script src="http://cdn/g.js"></script>',
                '<style>@import url("http://x/y.css");</style>',
                '<style>body{background:url(https://x/a.png)}</style>'):
        try:
            assert_determinism(bad); raise AssertionError(f"should have failed: {bad}")
        except CompositionAssertionError:
            pass


def test_segmenter_splits_english_sentences():
    # V19: latin "." was not a sentence boundary → an English paragraph became one
    # wall-of-text beat. Now it splits, while decimals ("3.14", "$5.5") stay intact.
    from monoline.pipeline.segment import SentenceSegmenter, segment_text
    beats = segment_text("Deep sea creatures glow. This is not sunlight. It is chemistry.")
    assert beats == ["Deep sea creatures glow.", "This is not sunlight.", "It is chemistry."]
    assert segment_text("The rate is 3.14 and the cost is $5.5 total.") == ["The rate is 3.14 and the cost is $5.5 total."]
    # merging two latin fragments keeps a space between them; CJK merges without one
    seg = SentenceSegmenter()
    assert seg._join("U.S.", "API.") == "U.S. API."
    assert seg._join("深海", "发光") == "深海发光"


def test_brand_logo_renders_in_lockup():
    # V25: a brand logo (composition-relative image) shows in #brand; empty → text only.
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme, Brand
    from monoline.compose.engine import render_composition
    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    t = Timings.from_durations(["第一拍。"], [3.0])
    scenes = [{"i": 0, "kind": "title", "slots": {"headline": "第一拍"}}]
    with_logo = render_composition(t, ScenePlan(theme=theme, brand=Brand(label="Acme", logo="assets/logo-ab12.png"), scenes=scenes))
    assert 'class="brand-logo" src="assets/logo-ab12.png"' in with_logo
    assert ">Acme<" in with_logo  # label still present beside the logo
    no_logo = render_composition(t, ScenePlan(theme=theme, brand=Brand(label="Acme"), scenes=scenes))
    assert '<img class="brand-logo"' not in no_logo   # CSS rule is always present; the <img> is not


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


def test_llm_not_configured_raises(monkeypatch):
    import asyncio
    from monoline.settings import Settings
    from monoline.llm import client as llm_client
    from monoline.llm.client import LLMNotConfigured, Target, generate_script

    # Nothing reachable: neither MONOLINE_LLM_* nor a local Ollama. (detect() would
    # otherwise find the developer's running Ollama and really call it.)
    monkeypatch.setattr(llm_client, "detect", lambda *a, **k: Target(source="none", detail="no where to go"))

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


def test_render_requests_the_streaming_path_v46():
    """V46 root cause: we never set workers, so the producer picks auto (4 on a 10-core
    Mac). Multi-worker capture on macOS is screenshot-based and CANNOT stream, so every
    frame goes to disk — a 110s @ 60fps 1080p render asked for 6.9 GB of temp space and
    died with rc=1 when the volume had 2.9 GB free. mp4/mov stream at one worker, so both
    render paths must say so explicitly."""
    from monoline.hf.cli import RENDER_WORKERS, _render_argv, _render_payload

    assert RENDER_WORKERS == 1
    argv = _render_argv("/proj", "/out.mp4", fps=60, quality="standard", fmt="mp4")
    assert argv[0] == "render" and "--workers" in argv
    assert argv[argv.index("--workers") + 1] == "1"
    assert argv[argv.index("--fps") + 1] == "60"

    payload = _render_payload("/proj", "/out.mp4", fps=60, quality="high", fmt="mp4")
    assert payload["workers"] == 1
    assert payload["fps"] == 60 and payload["format"] == "mp4"
    assert payload["quality"] in ("standard", "high", "draft", "looks", "delivery")

    # and when a render does fail, keep the sentence that says what to do
    from monoline.hf.cli import _tail_error

    stderr = ("[INFO] streaming-encode gate {\"reason\":\"multi_worker\"}\n"
              "  25%  Failed: Disk capture may need ~6877.1 MB\n\n"
              "✗  Render failed\n\n"
              "   Disk capture may need ~6877.1 MB of temporary frame storage, "
              "but only 2856.6 MB is free at /tmp/work-x. This render landed on disk because "
              "it is multi-worker screenshot capture. Re-run with --workers 1, or free up disk space.\n"
              "   Try --docker for containerized rendering\n")
    msg = _tail_error(stderr)
    assert msg.startswith("Disk capture may need") and "6877.1" in msg and "2856.6" in msg
    assert msg.endswith("Try --docker for containerized rendering")


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
    assert '<div class="shot"><img src="assets/b.jpg"' in html  # dedicated image kind
    # image kind must NOT also emit the generic scene-media block — count actual emitted
    # blocks (class="scene-media"), not the bare token, which also appears in CSS + the
    # stagger JS selector. Only scene-0 (statement w/ image) emits one; the image kind emits zero.
    assert html.count('class="scene-media"') == 1
    # V33: both entrances go through the same treated frame, not a bare <img>
    assert html.count('<div class="shot">') == 2


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
    assert pick_icon("营收增长了 30%") == "arrow_up"      # growth beats a generic chart glyph
    assert pick_icon("速度提升到毫秒级") == "bolt"
    assert pick_icon("这是一个模型架构") == "cpu"
    assert pick_icon("需要注意口径") == "info"
    assert pick_icon("完全无关的普通句子啊") == ""
    # every mapped icon must exist in the library (no typos → silent blank)
    from monoline.compose.icons import _ICON_KEYWORDS
    for icon, _ in _ICON_KEYWORDS:
        assert icon in _ICONS, icon


def test_icon_library_vendored_scale_and_uniqueness():
    """V31: the Lucide-backed table is big, provenance-tagged, and has no two
    keys drawing the same glyph (that made grid/grid2 identical in the picker)."""
    import collections
    import json
    import subprocess
    import sys

    from monoline.compose.icons import _ICONS, names

    assert len(_ICONS) >= 100
    raw = json.loads((pathlib.Path(__file__).resolve().parents[1]
                      / "src/monoline/compose/data/icons.json").read_text(encoding="utf-8"))
    assert "lucide" in raw["_source"].lower()
    dupes = {k: v for k, v in collections.Counter(_ICONS.values()).items() if v > 1}
    assert not dupes, f"identical geometry under different keys: {dupes}"
    assert names() == sorted(_ICONS)
    # data/icons.json must match what the vendored sprite yields today
    r = subprocess.run([sys.executable, "scripts/build_icons.py", "--check"],
                       capture_output=True, text=True, cwd=pathlib.Path(__file__).resolve().parents[1])
    assert r.returncode == 0, r.stdout + r.stderr


def test_icon_keywords_are_specific_enough():
    """V31: substring matching means a short keyword is a false-positive machine.

    Measured on 223 real beats from the local job DB: '位'→binary fired on 「单位」,
    'rain'→droplet on 「training」, 'ai'→brain_circuit on 「said」. Coverage cost
    32.7%→25.6%, and every dropped hit was noise.
    """
    from monoline.compose.icons import _ICON_KEYWORDS, pick_icon

    def is_ascii(s):
        return all(ord(c) < 128 for c in s)

    for icon, kws in _ICON_KEYWORDS:
        for kw in kws:
            assert kw == kw.lower(), (icon, kw)
            if is_ascii(kw):
                assert len(kw) >= 4, (icon, kw)
            else:
                assert len(kw.strip()) >= 2, (icon, kw)

    assert pick_icon("这个单位很高") != "binary"
    assert pick_icon("the training data was clean") != "droplet"
    assert pick_icon("he said it was fine") != "brain_circuit"
    assert pick_icon("点击开始播放") == "play"
    assert pick_icon("效率之高几乎不产生热量") == "bolt"


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


def test_graphic_kit_layers_render_v31b():
    """V31b: the three static depth layers every designed deck has — dot texture,
    corner crop marks, per-scene folio — must be in the composition, and the folio
    must count scenes, not segments or frames."""
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    t = Timings.from_durations(["第一拍。", "第二拍", "第三拍"], [3.0, 3.0, 3.0])
    plan = ScenePlan(theme=theme, scenes=[
        {"i": 0, "kind": "title", "slots": {"eyebrow": "Acme", "headline": "第一拍", "icon": "sparkles"}},
        {"i": 1, "kind": "statement", "slots": {"headline": "第二拍"}},
        {"i": 2, "kind": "stat", "slots": {"value": "30", "label": "第三拍"}}])
    html = render_composition(t, plan)

    assert '<div id="grain"' in html and "background-size: 26px 26px" in html
    assert html.count('<div id="ticks"') == 1 and html.count("<i></i>") >= 4
    # one folio per scene, zero-padded, sharing the same total
    for i in range(3):
        assert f'<span class="f-now">{i + 1:02d}</span>' in html
    assert html.count('class="folio"') == 3 and ">03</span>" in html
    # the icon plate is a plate only when an icon is present
    assert 'class="scene-icon"' in html and html.count('class="scene-icon"') == 1
    assert ".eyebrow::before" in html                                   # badge dot
    assert "background-size: 26px 26px" in html and "url(http" not in html   # still offline


def test_viz_kit_sparkline_donut_delta():
    """V31c: the three new primitives refuse to draw when the data isn't there."""
    import re
    from monoline.compose.viz import delta, donut, sparkline

    # a slot can hold "1.2 / 1.9 / 2.4" as one string — splitting it is the whole
    # point; reading it char-by-char drew a jagged lie in the first snapshot.
    s = sparkline("1.2 / 1.9 / 2.4 / 3.1 / 4.8")
    pts = [tuple(map(float, p.split(","))) for p in re.search(r'points="([^"]+)"', s).group(1).split(" ")]
    assert len(pts) == 5 and pts[0][0] < pts[-1][0]
    assert pts[0][1] > pts[-1][1]                                   # rising values → rising line (y flips)
    assert sparkline(["1.2", "1.9", "2.4", "3.1", "4.8"]) == s      # same markup either way
    assert sparkline(["营收", "利润"]) == ""                          # no numbers, no chart
    assert sparkline(["42"]) == "" and sparkline([]) == ""
    assert sparkline("5 / 5 / 5").count("48.0") >= 3                 # flat series sits mid-box, no div-by-0

    d = donut("45 / 30 / 15 / 10")
    assert d.count("<circle") == 5                                   # track + 4 segments
    assert donut("45 / 30 / 15 / 10 / 5").count("<circle") == 5      # capped at four tones
    assert donut("45") == "" and donut("a / b") == ""

    assert delta("+12%") == {"dir": "up", "sign": "+", "num": "12", "suffix": "%"}
    assert delta("−3.4")["dir"] == "down"
    assert delta("环比下降 5 个点") == {"dir": "down", "sign": "−", "num": "5", "suffix": "个点"}
    assert delta("效率提升 3 倍")["suffix"] == "倍"
    assert delta("营收 3.2 亿") is None                              # a level, not a change
    assert delta("") is None and delta(None) is None


def test_stat_scene_renders_delta_and_spark():
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    t = Timings.from_durations(["营收 4.8 亿"], [4.0])
    plan = ScenePlan(theme=theme, scenes=[{"i": 0, "kind": "stat", "slots": {
        "value": "4.8", "unit": "亿", "label": "营收", "delta": "-12%", "trend": "1.2 / 1.9 / 2.4 / 4.8"}}])
    html = render_composition(t, plan)
    assert 'class="delta down"' in html and "−12%</span>" in html
    assert 'class="spark"' in html and "sl-dot" in html
    plain = render_composition(t, ScenePlan(theme=theme, scenes=[
        {"i": 0, "kind": "stat", "slots": {"value": "4.8", "label": "营收"}}]))
    assert "class=\"delta" not in plain and 'class="spark"' not in plain


def test_bars_kind_v31d():
    """V31d: unrelated numeric metrics become a bar chart — not a table, and not a
    funnel. A decreasing list alone is not a flow losing population."""
    import json
    import re
    from pathlib import Path
    from monoline.ir.sceneplan import KINDS, ScenePlan, Theme
    from monoline.ir.timings import Timings
    from monoline.compose.engine import render_composition
    from monoline.pipeline.planner import plan_scenes

    assert "bars" in KINDS
    cases = [
        ("速度：120，功耗：45，成本：30", "bars"),          # decreasing, but three metrics
        ("曝光：12000，点击：3400，下单：520", "funnel"),   # decreasing AND one flow
        ("价格：下调一半；能力：提升三倍", "table"),          # not numeric
        ("甲：10，乙：10，丙：10", "table"),                # no ranking to show
    ]
    for text, want in cases:
        got = [s for s in plan_scenes(["开场。", text], brand="Monoline") if s["i"] == 1][0]
        assert got["kind"] == want, (text, got["kind"], want)

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    t = Timings.from_durations(["速度 120，功耗 45，成本 30"], [4.0])
    plan = ScenePlan(theme=theme, scenes=[{"i": 0, "kind": "bars", "slots": {
        "title": "三项指标", "rows": [{"k": "速度", "v": "120"}, {"k": "功耗", "v": "45"}, {"k": "成本", "v": "30"}],
        "verbatim": True}}])
    html = render_composition(t, plan)
    widths = [float(w) for w in re.findall(r'class="bfill[^"]*"\s+style="width:([\d.]+)%"', html)]
    assert widths == [100.0, 37.5, 25.0]                    # normalized to the max
    assert html.count('<span class="bk">') == 3              # rows (the leader now carries a class too)
    assert 'class="bfill top"' in html                      # the leader carries the accent
    assert "bfill" in html and 'class="btrack"' in html


def test_kpi_and_timeline_kinds_v31d():
    """V31d: colon-free metric lists and dated milestones were falling through to a
    plain sentence (or, worse, to a funnel because the numbers happened to shrink)."""
    import json
    from pathlib import Path
    from monoline.ir.sceneplan import KINDS, ScenePlan, Theme
    from monoline.ir.timings import Timings
    from monoline.compose.engine import render_composition
    from monoline.pipeline.planner import plan_scenes

    assert {"kpi", "timeline"} <= set(KINDS)

    def kind_of(b):
        return [s for s in plan_scenes(["开场。", b], brand="Monoline") if s["i"] == 1][0]

    k = kind_of("日活 120 万，留存 45%，营收 3.2 亿")
    assert k["kind"] == "kpi"                      # mixed units → not comparable by length
    assert [r["k"] for r in k["slots"]["rows"]] == ["日活", "留存", "营收"]
    assert [r["v"] for r in k["slots"]["rows"]] == ["120万", "45%", "3.2亿"]   # no "45 %" gap
    # 留存 used to be a funnel marker word: as a standalone rate it must not be one
    assert kind_of("曝光 12000 人、点击 3400 人、下单 520 人")["kind"] == "funnel"
    assert kind_of("速度 120，功耗 45，成本 30")["kind"] == "bars"

    t = kind_of("2019 年创业，2021 年拿 A 轮，2024 年上市")
    assert t["kind"] == "timeline"
    assert t["slots"]["rows"] == [{"k": "2019 年", "v": "创业"}, {"k": "2021 年", "v": "拿 A 轮"},
                                  {"k": "2024 年", "v": "上市"}]
    # one lonely year is not a timeline
    assert kind_of("这事发生在 2019 年的一天下午")["kind"] != "timeline"

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations(["指标", "里程碑"], [4.0, 4.0])
    plan = ScenePlan(theme=theme, scenes=[
        {"i": 0, "kind": "kpi", "slots": {"title": "本月", "verbatim": True,
            "rows": [{"k": "日活", "v": "120 万"}, {"k": "留存", "v": "45%"}]}},
        {"i": 1, "kind": "timeline", "slots": {"title": "历程", "verbatim": True,
            "rows": [{"k": "2019 年", "v": "创业"}, {"k": "2024 年", "v": "上市"}]}}])
    html = render_composition(tim, plan)
    assert html.count('class="kcard"') == 2 and 'class="kv"' in html
    assert html.count('class="tl-p') == 2 and 'class="tl-p now"' in html   # last tick accented
    rail = [ln.strip() for ln in html.splitlines() if ".tl-rail" in ln and "from(" in ln]
    assert len(rail) == 1 and "scaleX: 0" in rail[0]                       # landscape draws sideways
    tall = ScenePlan(theme=theme, canvas={"width": 1080, "height": 1920}, scenes=plan.scenes)
    rail_p = [ln.strip() for ln in render_composition(tim, tall).splitlines()
              if ".tl-rail" in ln and "from(" in ln]
    assert len(rail_p) == 1 and "scaleY: 0" in rail_p[0]                   # portrait draws top-down
    for k2 in ("kpi", "timeline"):
        from monoline.compose.engine import _TEMPLATES
        assert (_TEMPLATES / "kinds" / f"{k2}.html.j2").exists()


def test_share_and_trend_kinds_v31e():
    """V31e: donut() and sparkline() had no automatic entry point. Two guards matter:
    a share ring only makes sense when the parts exhaust one whole, and a line only
    makes sense when there is a run of numbers to connect."""
    import json
    from pathlib import Path
    from monoline.ir.sceneplan import KINDS, ScenePlan, Theme
    from monoline.ir.timings import Timings
    from monoline.compose.engine import render_composition
    from monoline.pipeline.planner import plan_scenes

    assert {"share", "trend"} <= set(KINDS)

    def kind_of(b):
        return [s for s in plan_scenes(["开场。", b], brand="Monoline") if s["i"] == 1][0]

    sh = kind_of("市场份额：芯片 45%，整机 30%，服务 25%")
    assert sh["kind"] == "share" and sh["slots"]["title"] == "市场份额"     # lead label is the title
    assert [r["v"] for r in sh["slots"]["rows"]] == ["45%", "30%", "25%"]
    # 45+30+10 ≠ a whole → these are three rates, not one pie
    assert kind_of("芯片 45%，整机 30%，服务 10%")["kind"] == "kpi"
    # 'iOS 占 30%' puts a verb between label and number; the pattern must still read it
    assert kind_of("安卓占 45%，iOS 占 30%，其他 25%")["kind"] == "share"

    tr = kind_of("季度营收 1.2 亿、1.9 亿、2.4 亿、3.1 亿")
    # unit stays glued to the number (V31d convention) — it is what the axis labels show
    assert tr["kind"] == "trend" and tr["slots"]["series"] == ["1.2亿", "1.9亿", "2.4亿", "3.1亿"]
    assert kind_of("转化率从 12% 涨到 48%")["kind"] == "trend"             # 2 points + 从…到…
    assert kind_of("速度 120，功耗 45，成本 30")["kind"] == "bars"          # 3 numbers, no order claimed

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations(["份额", "走势"], [4.0, 4.0])
    plan = ScenePlan(theme=theme, scenes=[
        {"i": 0, "kind": "share", "slots": {"title": "份额", "verbatim": True, "rows": [
            {"k": "芯片", "v": "45%"}, {"k": "整机", "v": "30%"}, {"k": "服务", "v": "25%"}]}},
        {"i": 1, "kind": "trend", "slots": {"title": "季度营收", "verbatim": True,
            "series": ["1.2 亿", "1.9 亿", "2.4 亿", "3.1 亿"]}}])
    html = render_composition(tim, plan)
    assert 'class="donut"' in html and html.count("<circle") >= 4
    assert html.count('class="legend"') == 1 and 'class="sw s3"' in html   # legend tone 3 exists
    assert 'class="spark"' in html and '<div class="tv">3.1 亿</div>' in html   # newest value is the hero
    assert html.count('class="tlabels"') == 1
    assert "clipPath" in html                                               # the line wipes in


def test_shape_kinds_are_derived_not_hand_listed():
    """The last beat is normally turned into a `summary`; a kind that carries its own
    picture must outrank that. A hand-maintained list went stale the moment new kinds
    landed — a timeline ending a script silently became a summary."""
    from monoline.ir.sceneplan import KINDS
    from monoline.pipeline.planner import _SHAPE_KINDS, _TEXT_KINDS, plan_scenes

    assert _SHAPE_KINDS | _TEXT_KINDS == set(KINDS)
    assert not (_SHAPE_KINDS & _TEXT_KINDS)
    assert {"bars", "kpi", "timeline", "share", "trend"} <= _SHAPE_KINDS

    scenes = plan_scenes(["开场。", "中间说一句。", "2019 年创业，2021 年拿下 A 轮，2024 年上市。"])
    assert scenes[-1]["kind"] == "timeline", scenes[-1]


def test_matrix_kind_v31f():
    """V31f: a 2×2 grid claims two dimensions, so it is only earned when the beat says
    so — four parallel items alone are a list."""
    import json
    from pathlib import Path
    from monoline.ir.sceneplan import KINDS, ScenePlan, Theme
    from monoline.ir.timings import Timings
    from monoline.compose.engine import render_composition
    from monoline.pipeline.planner import plan_scenes

    assert "matrix" in KINDS

    def scene_of(b):
        return [s for s in plan_scenes(["开场。", b], brand="Monoline") if s["i"] == 1][0]

    m = scene_of("时间管理四象限：重要紧急、重要不紧急、紧急不重要、既不紧急也不重要")
    assert m["kind"] == "matrix" and m["slots"]["title"] == "时间管理四象限"
    assert len(m["slots"]["cells"]) == 4
    assert m["slots"]["x_axis"] == ""                       # nothing named an axis → none drawn
    # the same four items without the quadrant word stay a list
    assert scene_of("我们有四类客户：学生、上班族、自由职业、退休人群")["kind"] == "list"
    # a matrix word with only three items is not a quadrant
    assert scene_of("这套方法是个矩阵：快、省、好")["kind"] != "matrix"
    # axis words are read, with their particles stripped (「按效率轴」→ 效率)
    ax = scene_of("按效率轴和规模维度切成矩阵：高效率高规模、高效率高成本、低效率高规模、低效率高成本")
    assert (ax["slots"]["x_axis"], ax["slots"]["y_axis"]) == ("效率", "规模")

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations(["四象限"], [4.0])
    html = render_composition(tim, ScenePlan(theme=theme, scenes=[
        {"i": 0, "kind": "matrix", "slots": {"title": "时间管理", "x_axis": "紧急", "y_axis": "重要",
            "cells": ["重要紧急", "重要不紧急", "紧急不重要", "既不紧急也不重要"], "verbatim": True}}]))
    assert html.count('class="mcell"') == 4
    assert '<span class="m-q">01</span>' in html and '<span class="m-q">04</span>' in html
    assert 'class="m-axis m-xaxis"' in html and 'class="m-axis m-yaxis"' in html
    plain = render_composition(tim, ScenePlan(theme=theme, scenes=[
        {"i": 0, "kind": "matrix", "slots": {"title": "T", "x_axis": "", "y_axis": "",
            "cells": ["a", "b", "c", "d"], "verbatim": True}}]))
    assert "m-axis m-xaxis" not in plain and "m-axis m-yaxis" not in plain
    # ^ element-level on purpose: the stylesheet always contains `.m-xaxis`, so a bare
    # substring test would pass even when no axis is rendered.


def test_text_scenes_get_a_skeleton_rail():
    """V31g: measured on 212 real beats, 57% of slides are a plain statement and the
    headline median is 10 chars with a number in only 2% of them — there is nothing to
    hang emphasis on, so the text kinds share one structural rail instead."""
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations(["说一句。", "第二章节", "收个尾", "列四项"], [3.0, 3.0, 3.0, 3.0])
    plan = ScenePlan(theme=theme, scenes=[
        {"i": 0, "kind": "statement", "slots": {"headline": "说一句"}},
        {"i": 1, "kind": "section", "slots": {"title": "第二章节", "index": "02"}},
        {"i": 2, "kind": "summary", "slots": {"headline": "收个尾"}},
        {"i": 3, "kind": "list", "slots": {"title": "列四项", "items": ["甲", "乙", "丙", "丁"]}}])
    html = render_composition(tim, plan)
    rail = '.k-statement, .k-section, .k-summary { position: relative; padding-left: 44px; }'
    assert rail in html
    assert html.count("linear-gradient(180deg, var(--accent),") >= 1        # the rail itself
    assert ".k-section::before" in html and ".k-summary::before" in html
    assert ".k-list::before" not in html                                    # data kinds keep their own frame


def test_scene_light_wash_cycles_v32():
    """V32: one global glow meant every slide carried a pixel-identical background, so a
    run of text beats read as the same frame. The wash cycles by scene index."""
    import re
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations(["一。", "二。", "三。", "四。"], [3.0, 3.0, 3.0, 3.0])
    scenes = [{"i": i, "kind": "statement", "slots": {"headline": f"第{i}句"}} for i in range(4)]
    html = render_composition(tim, ScenePlan(theme=theme, scenes=scenes))
    washes = re.findall(r'class="wash w(\d)"', html)
    assert washes == ["1", "2", "3", "1"]                     # deterministic cycle, drifts on dissolve
    assert html.count('class="wash') == 4
    for tone in ("w1", "w2", "w3"):
        assert f".scene .wash.{tone}" in html
    # static decoration: the timeline must never touch it (it rides the scene opacity)
    assert "wash" not in html.split("<script>")[1]


def test_image_treatment_and_ken_burns_v33():
    """V33: a raw uploaded photo was the one element that ignored the brand language —
    its own colours, its own contrast, no depth, and dead still. Shots are now normalised
    (grayscale + one accent wash), framed (hairline/radius/shadow) and drifted."""
    import json
    import re
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations(["有图。", "彩色图。", "没图。"], [4.0, 3.0, 3.0])
    scenes = [
        {"i": 0, "kind": "image", "slots": {"image": "assets/a.png", "headline": "有图"}},
        {"i": 1, "kind": "image", "slots": {"image": "assets/b.png", "headline": "彩色", "image_tone": "color"}},
        {"i": 2, "kind": "statement", "slots": {"headline": "没图"}},
    ]
    html = render_composition(tim, ScenePlan(theme=theme, scenes=scenes))
    css, js = html.split("<style>")[1].split("</style>")[0], html.split("<script>")[1]

    # tone: any photo is pulled into the monochrome brand language…
    assert "grayscale(1)" in css and ".shot img" in css
    # …with one accent wash and real depth, and the frame clips the drift
    assert ".shot { position: relative; overflow: hidden" in css
    assert "mix-blend-mode: soft-light" in css and "box-shadow: 0 30px 60px -34px rgb(0 0 0" in css
    # portrait/square lift the frame by --scene-scale, so a raw 94vw cap ran the shot off
    # the canvas — every shot cap is divided back out
    assert "max-width: calc(min(1400px, 94vw) / var(--scene-scale))" in css
    assert "max-height: calc(72vh / var(--scene-scale))" in css
    assert "94vw)" not in css.replace("calc(min(1400px, 94vw) / var(--scene-scale))", "")
    # per-scene escape hatch, driven by a slot the Studio can edit
    assert '<div class="shot tone-color">' in html
    assert ".shot.tone-color img { filter: none; }" in css
    assert ".shot.tone-color::after { display: none; }" in css

    # motion: one push-in per shot, spanning the scene it lives in (4.0s → 3.5s of drift).
    # "none" = constant angular velocity; a keyed scale is the only spatial property used.
    drifts = re.findall(
        r'fromTo\("#scene-(\d+) \.shot img", \{ scale: ([\d.]+) \},\s*'
        r'\{ scale: ([\d.]+), duration: ([\d.]+), ease: "(\w+)" \}, ([\d.]+)\)', html)
    assert drifts == [("0", "1.02", "1.075", "3.5", "none", "0.2"),
                      ("1", "1.02", "1.075", "2.5", "none", "4.2")]
    assert "scene-2 .shot" not in js                        # nothing to drift without an image


def test_reveal_density_scales_with_dwell_v34():
    """V34: every item reveal used a fixed 0.1s gap, so an 8s narration beat laid out its
    whole slide in half a second and then held a dead frame for 7.5s."""
    import json
    import re
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    durs = [1.2, 2.0, 4.0, 9.0]
    tim = Timings.from_durations(["一。", "二。", "三。", "四。"], durs)
    rows = [{"k": f"项{j}", "v": f"值{j}"} for j in range(5)]
    scenes = [{"i": i, "kind": "table", "slots": {"title": f"表{i}", "rows": rows}} for i in range(4)]
    html = render_composition(tim, ScenePlan(theme=theme, scenes=scenes))

    got = [float(a) for a in re.findall(r'\.row, #scene-\d+ \.brow".*?amount: ([\d.]+)', html, re.S)]
    assert got == [0.22, 0.68, 1.36, 2.6]          # grows with dwell, floored, then capped
    for sd, d in zip(got, durs):
        assert 0.28 + sd + 0.7 <= d + 1e-6         # last item settles before the scene leaves
    # ratchet: item reveals are all amount-based now; the only fixed gap left is the
    # 3-element icon→eyebrow→sub cascade, which should stay snappy
    assert set(re.findall(r"stagger: (?:\{ amount: [\d.]+|([\d.]+))", html)) <= {"0.09", ""}


def test_real_job_defects_v35():
    """Three defects found by snapshotting every beat of a real 15-line job."""
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition
    from monoline.pipeline.planner import RulePlanner, _trend

    p = RulePlanner()

    # 1. a falling line drawn through two incomparable numbers states something the
    #    script never said — 300 字 and 21.7 秒 are not a series
    assert _trend("实测数据：一段 300 字的稿子，从粘贴到出片平均 21.7 秒。") == ("", [])
    assert p._classify(0, "实测数据：一段 300 字的稿子，从粘贴到出片平均 21.7 秒。")["kind"] != "trend"
    # …while genuine series still read as one
    assert _trend("季度营收：1.2 亿、1.9 亿、2.4 亿、3.1 亿。")[1] == ["1.2亿", "1.9亿", "2.4亿", "3.1亿"]
    assert _trend("渗透率从 12% 涨到 48%。")[1] == ["12%", "48%"]

    # 2. the enumeration silently dropped its first and last items
    line = "它把整条链路拆成七步：写稿、配音、切分、分镜、字体、合成、渲染。"
    items = p._classify(0, line)["slots"]["items"]
    assert items == ["写稿", "配音", "切分", "分镜", "字体", "合成", "渲染"]

    # 4. the verb and the discourse lead-in were sliced into the card labels
    #    (「6% 分镜判定只」「42% 其中配音」 on the real job)
    from monoline.pipeline.planner import _kpis
    _, cards = _kpis("其中配音占 42%，渲染占 33%，分镜判定只占 6%。")
    assert [c["k"] for c in cards] == ["配音", "渲染", "分镜判定"]
    assert [c["v"] for c in cards] == ["42%", "33%", "6%"]

    # 3. display type orphaned: a 200px title split 「剪辑」 across the break
    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations(["标题。"], [3.0])
    html = render_composition(tim, ScenePlan(theme=theme, scenes=[{"i": 0, "kind": "title", "slots": {"headline": "标题"}}]))
    css = html.split("<style>")[1].split("</style>")[0]
    rules = [ln for ln in css.splitlines() if "text-wrap: balance" in ln]
    # the V35 rule itself must list every display-text selector (later kinds may add their own)
    v35 = [ln for ln in rules if ".headline," in ln and ".cap > .inner" in ln]
    assert len(v35) == 1
    for sel in (".headline", ".s-title", ".term", ".q", ".d-title", ".cap > .inner"):
        assert sel in v35[0]


def test_peak_marker_v36():
    """V36: a designed slide points at the one number that matters. The marker must come
    from the same geometry helper as the line, or it drifts off its own point."""
    from monoline.compose.viz import peak_marker, sparkline, _points

    m = peak_marker(["1.2亿", "3.6亿", "1.9亿", "2.4亿"], w=820, h=200)
    assert m["value"] == "3.6亿" and m["index"] == 1
    assert (m["x"], m["y"]) == _points([1.2, 3.6, 1.9, 2.4], 820, 200)[1]
    assert peak_marker(["1.2亿", "1.9亿", "2.4亿"], w=820, h=200) is None    # peak is the hero
    assert peak_marker(["1.2亿", "3.6亿"], w=820, h=200) is None             # two points, no shape
    assert peak_marker(["甲", "乙", "丙"], w=820, h=200) is None              # nothing numeric
    # refactor guard: extracting _points must not move a single pixel of the line
    assert sparkline(["1", "2"], w=100, h=40) == (
        '<svg class="spark" viewBox="0 0 100 40" aria-hidden="true">'
        '<polyline class="sl-line" points="10.0,30.0 90.0,10.0" fill="none" stroke-width="3" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle class="sl-dot" cx="90.0" cy="10.0" r="5"/></svg>')


def test_peak_annotation_and_dense_list_v36():
    """V36 annotation layer + the row-height fix V35b needed once a 7-item list existed."""
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations(["一。", "二。", "三。"], [6.0, 6.0, 6.0])
    scenes = [
        {"i": 0, "kind": "trend", "slots": {"title": "季度营收", "series": ["1.2亿", "3.6亿", "1.9亿", "2.4亿"]}},
        {"i": 1, "kind": "trend", "slots": {"title": "持续增长", "series": ["1.2亿", "1.9亿", "2.4亿"]}},
        {"i": 2, "kind": "list", "slots": {"items": ["写稿", "配音", "切分", "分镜", "字体", "合成", "渲染"]}},
    ]
    html = render_composition(tim, ScenePlan(theme=theme, scenes=scenes))

    assert html.count('class="callout"') == 1                     # only the mid-series peak
    assert "3.6亿" in html.split('class="callout"')[1][:80]
    assert "峰值" in html.split('class="callout"')[1][:120]
    # the callout is placed from the peak's own viewBox coordinates, not eyeballed
    assert 'left: 33.74%; top: calc(5.0% + 20px)' in html
    # 7 rows must fit the same box 6 rows used to fill
    assert "--li-fs: 39px; --li-pad: 15px" in html
    assert "font-size: var(--li-fs, 46px)" in html


def test_annotation_layer_extends_v37():
    """V37: the same device on the charts that have no line to hang a dot on — and the
    bars' accent row used to be whichever row came first, asserting a winner freely."""
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition
    from monoline.compose.viz import argmax, max_drop

    assert argmax(["12%", "48%", "30%"]) == 1
    assert argmax(["12%", "48%", "48%"]) is None            # a tie names no winner
    assert argmax(["甲", "乙"]) is None
    assert max_drop(["1000", "800", "300", "260"]) == 2     # the 800 → 300 collapse
    assert max_drop(["100", "95", "90"]) is None            # nothing worth labelling

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations(["一。", "二。", "三。"], [6.0, 6.0, 6.0])
    scenes = [
        {"i": 0, "kind": "bars", "slots": {"title": "渠道", "rows": [
            {"k": "自营", "v": "12%"}, {"k": "分销", "v": "48%"}, {"k": "KA", "v": "30%"}]}},
        {"i": 1, "kind": "funnel", "slots": {"title": "链路", "stages": [
            {"k": "曝光", "v": "1000"}, {"k": "点击", "v": "800"}, {"k": "成交", "v": "300"}]}},
        {"i": 2, "kind": "kpi", "slots": {"title": "指标", "rows": [
            {"k": "日活", "v": "120万"}, {"k": "留存", "v": "45%"}]}},
    ]
    html = render_composition(tim, ScenePlan(theme=theme, scenes=scenes))
    s0, s1, s2 = (html.split('id="scene-%d"' % i)[1].split('id="scene-')[0] for i in (0, 1, 2))

    segs = s0.split('<span class="bk">')          # one segment per row, in authored order
    assert len(segs) == 4
    assert [i for i, g in enumerate(segs[1:]) if "vtag" in g] == [1]
    assert 'class="brow is-top"' in s0 and s0.count("is-top") == 1
    assert 'class="bfill top"' in s0
    assert "最高" in s0 and "流失最大" in s1
    assert "vtag" not in s2          # 120万 and 45% are not comparable → no ranking claim


def test_magnitude_parsing_v37():
    """「12万」 read as 12 ranked a funnel's widest stage as its narrowest, and the four
    bars all collapsed onto the readability floor — a funnel wearing a funnel's clothes."""
    from monoline.compose.viz import _value, argmax, funnel_widths, max_drop

    assert _value("12万") == 120000
    assert _value("3.4亿") == 340000000
    assert _value("1.2M") == 1200000
    assert _value("42%") == 42.0                  # a share is not a magnitude
    assert _value("9800") == 9800.0
    assert _value("没有数字") is None

    w = funnel_widths(["12万", "9800", "2100", "1900"])
    assert w == [100.0, 8.2, 4.0, 4.0]           # real shares, not four bars on the floor
    assert max_drop(["12万", "9800", "2100", "1900"]) == 1     # the real 92% collapse
    assert argmax(["12万", "9800", "2100"]) == 0


def test_statement_frame_and_clean_headlines_v38():
    """V38: a hairline over the headline frames a lone line into a block. Measured on 119
    real statement headlines (median 10 chars) — the first cut gated it to <=16 chars
    assuming long ones wrap, but a shrunk 24-char line still sits on one line and looked
    worse without the frame, so the gate is gone."""
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition
    from monoline.pipeline.planner import distill_keyword

    assert distill_keyword("……魅力得自己去挣。")[0] == "魅力得自己去挣"
    assert distill_keyword("——说到底，还是要回到取舍。")[0] == "说到底"

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations(["短。", "长。"], [4.0, 4.0])
    scenes = [{"i": 0, "kind": "statement", "slots": {"headline": "分镜不是配图"}},
              {"i": 1, "kind": "statement", "slots": {"headline": "Monoline 做的就是这件事：文本进，分镜出"}}]
    html = render_composition(tim, ScenePlan(theme=theme, scenes=scenes))
    assert html.count('class="top-rule"') == 2
    # V40: fitting to one line dropped a 24-char statement to 67px — body-text size on a
    # slide that should carry a single thought. Two lines keep it at display size.
    assert "font-size:calc(116px * var(--hl-scale,1))" in html.split('id="scene-1"')[1]
    assert "#scene-0 .top-rule" in html and "#scene-1 .top-rule" in html
    assert ".k-statement .top-rule" in html.split("<script>")[0]


def test_stat_ordinal_guard_and_age_unit_v39():
    """Found by rendering real stat beats from the corpus: 「这是第10句…」 became a giant
    10, and 「40岁」 lost its 岁 into the label leaving 「不像多岁的人」."""
    from monoline.pipeline.planner import RulePlanner
    k = lambda t: RulePlanner()._classify(0, t)["kind"]

    assert k("这是第10句用来撑拍数的话。") != "stat"
    assert k("根本不像40多岁的人。") != "stat"            # 40多 is a range, not a figure
    assert k("参会人数达到40人。") == "stat"              # the real figure still qualifies
    # a real quantity stays a stat — but the counter must travel with the number, not
    # get stranded in the label («全书一共讲了 个案例»)
    q = RulePlanner()._classify(0, "全书一共讲了7个案例。")
    assert q["kind"] == "stat" and q["slots"]["value"] == "7个"
    assert "个" not in q["slots"]["label"]
    sc = RulePlanner()._classify(0, "他今年40岁。")
    assert sc["kind"] == "stat" and sc["slots"]["value"] == "40岁"
    assert "岁" not in sc["slots"]["label"]
    assert k("它在 DeepSWE 基准上拿到 68.8%。") == "stat"   # the good case still works


def test_resume_cannot_downgrade_a_shaped_plan_v41():
    """Job 001a0d863e left two plan rows: v1(source=llm, 4 shaped beats) then
    v2(source=rules, none) — the resume's empty upgrade silently won."""
    from monoline.pipeline.runner import keep_richer_plan

    assert keep_richer_plan({"source": "llm"}, "rules") is True
    assert keep_richer_plan({"source": "llm"}, "llm") is False      # a newer shaped plan may replace
    assert keep_richer_plan({"source": "rules"}, "rules") is False  # nothing better to keep
    assert keep_richer_plan({"source": "manual"}, "rules") is False # a hand edit is not a downgrade guard
    assert keep_richer_plan(None, "rules") is False                 # first run


def test_source_boilerplate_never_becomes_a_headline_v42():
    """Gap 11a: 4 beats in the real corpus were a bare URL / 链接： / a republication
    notice rendered at 116px display size. Three hard shapes, 0 measured false positives."""
    from monoline.pipeline.planner import RulePlanner
    p = RulePlanner()

    for t in ["//www.zhihu.com/question/2068641114068988689/a", "链接：https:",
              "商业转载请联系作者获得授权，非商业转载请注明出处。", "https://example.com/x"]:
        sc = p._classify(0, t)
        assert sc["kind"] == "note" and sc["source"] == "rules:source-junk", t
        assert sc["slots"]["body"]

    # the prose my first loose detector wrongly flagged must not be swept up
    legit = ["君王将宫殿修得越来越高，在彰显国力、君威的同时，",
             "月球在高处，而古人对高处最直观的感受就是冷，越高越冷，",
             "终端BG董事长余承东现身合肥鸿蒙智行线下门店，",
             "他们也自知这样会使得自己的处境变得越加冷清、孤寂，让孤、寡、不穀、",
             "更神奇的是，顺着溪水往上找，最后往往不是找到一个大水潭，",
             "它在 DeepSWE 基准上拿到 68.8%。"]
    assert [t for t in legit if p._classify(0, t)["source"] == "rules:source-junk"] == []


def test_poster_kind_v43():
    """V43: a quoted document card with a highlighter stroke (modeled on real explainer
    channels), plus the escape discipline the <mark> injection surface demands."""
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme, KINDS
    from monoline.compose.engine import render_composition
    from monoline.compose.viz import highlight

    assert "poster" in KINDS
    assert highlight("今天的苦果是我们因循怠惰所致", ["因循怠惰"]) == \
        "今天的苦果是我们<mark>因循怠惰</mark>所致"
    assert highlight("没有命中的一句", ["不存在"]) == "没有命中的一句"
    # escape-then-match: a phrase carrying markup can never inject an element
    assert "<script>" not in highlight("正文 <script>alert(1)</script>", ["<script>alert(1)</script>"])
    assert highlight("a<b", ["a<b"]).count("<mark>") == 1

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations(["引语。"], [5.0])
    html = render_composition(tim, ScenePlan(theme=theme, scenes=[{"i": 0, "kind": "poster", "slots": {
        "tab": "CONCEPT NOTE / ARCHIVE", "body": "今天的苦果，是我们过去几年因循怠惰所致。",
        "hl": ["因循怠惰"], "by": "某集团老板", "verbatim": True}}]))
    assert 'class="p-tab"' in html and "<mark>因循怠惰</mark>" in html
    assert 'class="p-by"' in html and ".k-poster .p-body mark" in html
    # re-moding a beat to poster must never blank the slide: narration is the floor
    bare = render_composition(tim, ScenePlan(theme=theme, scenes=[{"i": 0, "kind": "poster", "slots": {}}]))
    assert 'class="p-body">引语。<' in bare and 'class="p-tab"' not in bare


def test_mode_library_catalog_is_the_single_source_v44():
    """V44: the Modes page and the inspector picker both read web/src/modes.tsx, so a
    kind that exists in sceneplan.KINDS but has no card becomes silently unpickable.
    One registry, one assertion — plus proof the bare <select> is actually gone."""
    import pathlib
    import re
    from monoline.ir.sceneplan import KINDS

    root = pathlib.Path(__file__).resolve().parents[2]
    src = (root / "web" / "src" / "modes.tsx").read_text()
    cards = re.findall(r'\{ kind: "([a-z]+)", zh: "([^"]+)", desc: "([^"]+)", glyph:', src)
    ids = [k for k, _, _ in cards]
    assert len(ids) == len(set(ids)), f"duplicate mode cards: {sorted(ids)}"
    assert set(ids) == set(KINDS), (
        f"catalog/KINDS drift: no card for {sorted(set(KINDS) - set(ids))}, "
        f"unknown card {sorted(set(ids) - set(KINDS))}")
    assert all(zh.strip() and desc.strip() for _, zh, desc in cards)

    studio = (root / "web" / "src" / "Studio.tsx").read_text()
    assert "<ModePicker value={d.kind} used={kindUsed}" in studio
    assert '<select className="fld" value={d.kind}' not in studio
    app = (root / "web" / "src" / "App.tsx").read_text()
    assert "h === \"modes\"" in app and "<ModesView />" in app


def test_showcase_kind_v45():
    """V45: a row of image cards — the third look from the reference screenshots.
    Each card owns its own asset, so the row can carry a caption per screenshot, and a
    card without an image still holds its slot instead of collapsing the grid."""
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme, KINDS
    from monoline.compose.engine import render_composition

    assert "showcase" in KINDS
    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations(["三个界面。"], [5.0])
    html = render_composition(tim, ScenePlan(theme=theme, scenes=[{"i": 0, "kind": "showcase", "slots": {
        "title": "三种界面", "image_tone": "mono",
        "rows": [{"k": "编辑器", "v": "三栏布局", "img": "assets/a.png"},
                 {"k": "首页", "v": "粘贴即出片", "img": "assets/b.png"},
                 {"k": "设置", "v": "品牌与音色"}]}}]))
    assert html.count('class="shot') == 2, "one card per uploaded asset"
    assert 'class="sc-ph"' in html and "未配图" in html
    assert 'src="assets/a.png"' in html and "三种界面" in html
    assert "tone-color" not in html.split('<div class="inner k-showcase">')[1], \
        "mono tone must not opt out of the shared treatment (the stylesheet always ships both rules)"
    # positive control: the same render with tone=color must light the class up
    color_html = render_composition(tim, ScenePlan(theme=theme, scenes=[{"i": 0, "kind": "showcase", "slots": {
        "title": "三种界面", "image_tone": "color",
        "rows": [{"k": "编辑器", "v": "", "img": "assets/a.png"}]}}]))
    assert 'class="shot tone-color"' in color_html.split('<div class="inner k-showcase">')[1]


def test_radial_screenshot_nodes_v45():
    """V45: a branch may carry the interface it names. node_imgs is an index-aligned
    overlay rather than a new node shape, so every plan already written with plain
    string nodes keeps rendering text-only chips."""
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations(["三个分支。"], [5.0])
    nodes = ["内容", "分发", "转化"]

    def frag(slots):
        html = render_composition(tim, ScenePlan(theme=theme, scenes=[{"i": 0, "kind": "radial", "slots": slots}]))
        return html.split('<div class="inner k-radial">')[1]

    plain = frag({"hub": "增长飞轮", "nodes": nodes})
    assert "has-img" not in plain and plain.count('class="pos"') == 4
    mixed = frag({"hub": "增长飞轮", "nodes": nodes, "node_imgs": ["assets/a.png", "", "assets/c.png"]})
    assert mixed.count('class="n-img"') == 2 and mixed.count("has-img") == 2
    assert mixed.count('class="node"') == 1, "the middle branch stays a text chip"
    assert 'src="assets/a.png"' in mixed and "assets/c.png" in mixed
    # an image chip is ~210px tall, so branches carrying one are capped (hub + 4 = 5 slots)
    many = frag({"hub": "H", "nodes": ["一", "二", "三", "四", "五"],
                 "node_imgs": ["assets/a.png", "", "", "", ""]})
    assert many.count('class="pos"') == 5
    texty = frag({"hub": "H", "nodes": ["一", "二", "三", "四", "五"]})
    assert texty.count('class="pos"') == 6, "text-only branches keep the old 5-branch cap"


def test_success_clears_the_stale_error_v46():
    """A job that failed and was then re-run successfully kept its failure text, so the
    API reported status=succeeded together with an error string — enough to send someone
    debugging a render that had already been fixed."""
    import asyncio
    import pathlib
    import tempfile
    from pathlib import Path

    src = (pathlib.Path(__file__).resolve().parents[1] / "src/monoline/pipeline/runner.py").read_text()
    line = [ln for ln in src.splitlines() if 'status="succeeded"' in ln and "update_job" in ln]
    assert len(line) == 1 and "error=None" in line[0], src

    async def run():
        from monoline.settings import Settings
        from monoline.queue.manager import JobManager

        s = Settings()
        s.app_dir = Path(tempfile.mkdtemp(prefix="monoline-err-"))
        s.ensure_dirs()
        m = JobManager(s)
        await m.repo.connect()
        jid = await m.repo.create_job(script_text="x", config={}, canvas={}, title="t", slug="t")
        await m.repo.update_job(jid, status="failed", error="render: disk capture shortfall")
        await m.repo.update_job(jid, status="succeeded", error=None)
        job = await m.repo.get_job(jid)
        assert job["status"] == "succeeded" and job["error"] is None
        await m.repo.close()

    asyncio.run(run())


def test_beat_rows_keep_their_height_v46():
    """A flex item with overflow:hidden gets min-height:0, so the default flex-shrink:1
    let every row in the .s3-beats scroll box collapse (19 rows measured 29px tall against
    60px of content) — the text was cut mid-line and painted over its neighbour instead of
    the list scrolling. Rows must opt out of shrinking."""
    import pathlib
    import re

    css = (pathlib.Path(__file__).resolve().parents[2] / "web" / "src" / "styles.css").read_text()
    strip = lambda s: re.sub(r"/\*.*?\*/", "", s, flags=re.S)  # prose must not satisfy a declaration check
    beat = strip(css.split(".beat {", 1)[1].split("}", 1)[0])
    assert "flex:none" in beat, ".beat rows shrink into each other inside the scroll box"
    assert "overflow:hidden" in beat, "the row still clips its own overflow"
    box = strip(css.split(".s3-beats {", 1)[1].split("}", 1)[0])
    assert "overflow-y:auto" in box, "the list is the scroller, not the rows"


def test_long_script_segments_and_llm_batches_v47():
    """V47: a long paste used to die with "70 beats exceeds cap 60" (1 of 45 real jobs),
    and the model got the whole weak-beat list in ONE prompt — which is exactly what
    OOMs a small local model and makes it answer with fewer items than asked."""
    import asyncio
    import json
    from types import SimpleNamespace

    from monoline.pipeline.segment import HARD_CAP, segment_text
    from monoline.llm import planner

    beats = segment_text("".join(f"这是第{i}个论点的说明句子，用来验证长文本。" for i in range(90)))
    assert len(beats) == 90, "the old 60-beat cap raised here instead of segmenting"
    # Derived from the constant, not a literal count: this assertion went stale the day the
    # cap moved, which is exactly how a guard test turns into a fake one.
    over = "论点说明句子用来验证。" * (HARD_CAP + 100)
    assert len(segment_text(over, hard_cap=None)) == HARD_CAP + 100, \
        "counting past the ceiling has to work — that number is the warning"
    try:
        segment_text(over)
        raise AssertionError("expected the hard cap to fire")
    except ValueError as e:
        assert "hard cap" in str(e)

    groups = planner._batches([(i, f"第{i}个论点的说明句子用来验证") for i in range(40)])
    assert len(groups) >= 4 and all(len(g) <= planner.BATCH_BEATS for g in groups)
    assert [x for g in groups for x in g] == [(i, f"第{i}个论点的说明句子用来验证") for i in range(40)]

    asked: list[list[int]] = []

    async def fake_chat(messages, **kw):
        idxs = [int(ln.split(".")[0]) for ln in messages[1]["content"].splitlines()]
        asked.append(idxs)
        if len(asked) == 2:
            raise planner.LLMError("simulated out of memory")
        return json.dumps({"scenes": [{"i": i, "kind": "definition",
                                       "slots": {"term": "论点", "gloss": "说明"}} for i in idxs]})

    async def run():
        b = [f"第{i}个论点的说明句子用来验证" for i in range(40)]
        s = [{"i": i, "kind": "statement", "slots": {}, "source": "rules"} for i in range(40)]
        real = planner.chat
        planner.chat = fake_chat
        try:
            out, stats = await planner.upgrade(None, b, s, target=SimpleNamespace(ok=True, model="fake"))
            # the budgets come from settings, so a small local context can shrink them
            asked.clear()
            tight = SimpleNamespace(llm_batch_beats=3, llm_batch_chars=900)
            out2, stats2 = await planner.upgrade(tight, b, s, target=SimpleNamespace(ok=True, model="fake"))
        finally:
            planner.chat = real
        assert len(out) == 40 and all(o["kind"] in ("statement", "definition") for o in out)
        assert stats["upgraded"] > 0, "one failed batch must not cancel the others"
        assert stats["batches"] == 4 and stats["failed_batches"] == 1
        assert len(out2) == 40 and stats2["batches"] == 14
        assert sum(len(a) for a in asked) == 40 and all(len(a) <= 3 for a in asked), \
            "settings must drive the batch size"

    asyncio.run(run())


def test_display_text_contract_v48():
    """V48: one owner for the on-slide punctuation rule (GB/T 15834 B.4 — a display line
    carries no terminal mark except ？ ！ …). The corpus measured 43 strings (13.8%) ending
    in punctuation, 17 (5.5%) ending mid-clause on 「，、：」, and 4 orphan quote marks left
    by segmentation; the rules were duplicated across 11 Python sites and none of them."""
    from monoline.pipeline.display_text import tidy, tidy_slots
    from monoline.pipeline.planner import RulePlanner

    assert tidy("中美双方同意将原定于11月10日到期的“贸易休战”协议延长两个月，") == \
        "中美双方同意将原定于11月10日到期的“贸易休战”协议延长两个月"
    assert tidy("探寻在经济领域可以取得哪些成果”") == "探寻在经济领域可以取得哪些成果"
    assert tidy("我们还是支持他们。”") == "我们还是支持他们"
    assert tidy("延长“贸易休战”协议两个月，将让双方“有更多时间,") == \
        "延长“贸易休战”协议两个月，将让双方“有更多时间"
    assert tidy("……魅力得自己去挣") == "魅力得自己去挣"
    assert tidy("成本，，很高。。") == "成本，很高"
    # what must survive: meaning, numbers, and machine values
    assert tidy("这到底是为什么？") == "这到底是为什么？"
    assert tidy("版本 v1.2") == "版本 v1.2"
    assert tidy("增长 3.5%") == "增长 3.5%"
    assert tidy("") == "" and tidy(None) == ""

    s = tidy_slots("statement", {"headline": "收尾。", "verbatim": False, "icon": "sparkle",
                                 "image": "assets/a.png", "image_tone": "mono"})
    assert s["headline"] == "收尾" and s["verbatim"] is False
    assert s["icon"] == "sparkle" and s["image"] == "assets/a.png" and s["image_tone"] == "mono"
    s2 = tidy_slots("list", {"title": "要点：", "items": ["快速启动。", "稳定支撑，"]})
    assert s2["title"] == "要点" and s2["items"] == ["快速启动", "稳定支撑"]

    scenes = RulePlanner().plan([
        "中美双方同意将原定于11月10日到期的“贸易休战”协议延长两个月，",
        "探寻在经济领域可以取得哪些成果”",
        "这到底是为什么？",
        "效率高达 68.8%，成本下降三成。",
    ])
    for sc in scenes:
        for k in ("headline", "title", "q", "body", "term", "gloss", "label", "hub"):
            v = sc["slots"].get(k)
            if isinstance(v, str) and v:
                assert not v.endswith(("。", "，", "、", "：", "；", ",")), (sc["kind"], k, v)
    assert any(sc["slots"].get("headline", "").endswith("？") for sc in scenes), \
        "a question headline keeps its ？"


def test_rotation_breaks_long_text_runs_v49():
    """V49: the corpus measured 96 beats (30.9%) inside a same-kind run longer than two,
    the longest run being 12 consecutive statements. Per-beat classification cannot see
    that, so a whole-piece pass converts the surplus beat into the most specific shape its
    own words support — and never invents copy."""
    import json
    from pathlib import Path
    from monoline.ir.sceneplan import ScenePlan, Theme, KINDS
    from monoline.ir.timings import Timings
    from monoline.compose.engine import render_composition
    from monoline.pipeline.planner import RulePlanner
    from monoline.pipeline.rotation import rebalance

    assert "split" in KINDS
    beat = "这是第一个论点的说明，后面还跟着足够长的解释内容与依据。"
    out = rebalance([{"i": i, "kind": "statement", "slots": {}, "source": "rules:default"}
                     for i in range(5)], [beat] * 5)
    assert [s["kind"] for s in out] == ["statement", "statement", "split", "statement", "statement"]
    assert out[2]["source"] == "rules:rotation"
    assert out[2]["slots"]["lead"] in beat and out[2]["slots"]["verbatim"] is True

    # a beat the segmenter cut mid-quotation stays a statement: splitting it again would
    # paint an orphan “ (real case from job 001a0d3b0c9c, beat 5)
    cut = "针对市场上流传的诸多说法，余承东在合肥门店现场表示：“经过这几年的合作发展，"
    three = [{"i": i, "kind": "statement", "slots": {}, "source": "rules:default"} for i in range(3)]
    kept = rebalance(three, ["第一句说明情况，后面还有足够的解释内容。",
                             "第二句说明情况，后面还有足够的解释内容。", cut])
    assert kept[2]["kind"] == "statement" and "“" not in (kept[2]["slots"].get("lead") or "")

    scenes = RulePlanner().plan(["开场白在这里。"] + [f"第{i}个观点说明现状，同时给出可执行的路径与依据。"
                                                    for i in range(8)])
    kinds = [s["kind"] for s in scenes]
    run = longest = 1
    for a, b in zip(kinds, kinds[1:]):
        run = run + 1 if a == b else 1
        longest = max(longest, run)
    assert longest <= 3, f"longest same-kind run {longest}: {kinds}"
    assert len({k for k in kinds if k != "statement"}) >= 2, kinds

    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations([beat], [5.0])
    html = render_composition(tim, ScenePlan(theme=theme, scenes=[
        {"i": 0, "kind": "split", "slots": {"lead": "第一个论点", "body": "后面还跟着足够长的解释内容",
                                            "verbatim": True}}]))
    assert 'class="inner k-split"' in html and 'class="sp-lead"' in html and "第一个论点" in html
    assert ".k-split .sp-body" in html and "grid-template-columns" in html


def test_statement_variants_v49b():
    """V49b: rotation converts a surplus text beat only when its own words support another
    shape — measured, that reaches ~1 beat in 6. The rest stay `statement`, so a deck of
    identical sentences still repeated one layout 12 times. Hence a content-free treatment
    axis: same kind, three settings, so the visible identity never repeats in a row."""
    import json
    import re
    from pathlib import Path
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.ir.timings import Timings
    from monoline.compose.engine import render_composition
    from monoline.pipeline.planner import RulePlanner
    from monoline.pipeline.rotation import rebalance, VARIANTS, VARIANT_KINDS

    # no clause, no quote, no k:v -> every alternative declines, so only the treatment can vary
    plain = "这一句没有任何可供改写的分隔信号"
    out = rebalance([{"i": i, "kind": "statement", "slots": {}, "source": "rules:default"}
                     for i in range(7)], [plain] * 7)
    assert [s["kind"] for s in out] == ["statement"] * 7
    assert [s["slots"]["variant"] for s in out] == \
        ["hero", "flush", "frame", "hero", "flush", "frame", "hero"]

    # the contract the metric depends on: adjacent slides never share kind AND treatment
    key = lambda scenes: [(s["kind"], (s.get("slots") or {}).get("variant")) for s in scenes]
    assert all(a != b for a, b in zip(key(out), key(out)[1:])), key(out)

    # a variant is only real if the template carries it and the CSS sets it apart from hero.
    # Match the element's class attribute, not the bare word: the shared stylesheet contains
    # `.k-statement.v-flush`, so `'v-flush' in html` would pass with the class never rendered.
    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    tim = Timings.from_durations([plain], [5.0])
    seen = {}
    for v in VARIANTS:
        html = render_composition(tim, ScenePlan(theme=theme, scenes=[
            {"i": 0, "kind": "statement", "slots": {"headline": "没有任何信号", "variant": v}}]))
        seen[v] = html
        assert f'class="inner k-statement v-{v}"' in html, f"{v}: template dropped slots.variant"
    # hero is the untouched centred layout; each other treatment needs the property that
    # actually changes the geometry. flush releases the 1400px cap where it is set (.sbody),
    # because lifting it on .inner alone measured a 44px move — not a different layout.
    # Read the declaration block, don't grep the file: the comment above the rule names the
    # same selectors.
    def rule(html, sel):
        m = re.search(re.escape(sel) + r"[^{]*\{([^}]*)\}", html)
        assert m, f"no rule for {sel}"
        return m.group(1)

    assert 'class="sbody sbody--ed sbody--flush"' in seen["flush"]
    assert "max-width: 100%" in rule(seen["flush"], ".sbody--flush")
    assert "text-align: left" in rule(seen["flush"], ".k-statement.v-flush")
    assert "border: 1px solid" in rule(seen["frame"], ".k-statement.v-frame")

    # rebalance must survive the planner tail (tidy_slots runs after it and leaves `variant` be)
    scenes = RulePlanner().plan([plain] * 6)
    got = [(s["kind"], s["slots"].get("variant")) for s in scenes if s["kind"] in VARIANT_KINDS]
    assert got and all(var in VARIANTS for _, var in got), got
    assert all(a != b for a, b in zip(got, got[1:])), got


def test_composed_css_stays_balanced():
    """A single unbalanced paren inside a declaration makes the browser swallow the
    NEXT rule during error recovery — one bad `color-mix(...)` silently killed `.frame`
    and collapsed every scene to the top-left, invisible to lint and to unit tests.
    Cheap structural guard for every theme × layout combination."""
    import json
    import re
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition

    tim = Timings.from_durations(["拍。"], [3.0])
    scenes = [{"i": 0, "kind": "statement", "slots": {"headline": "拍"}}]
    for tid in ("mono-ink", "mono-paper", "mono-noir", "mono-slate"):
        tokens = json.loads((Path("../design/tokens") / f"{tid}.json").read_text())["tokens"]
        theme = Theme(id=tid, tokens=tokens)
        for layout in ("minimal", "editorial", "bold"):
            html = render_composition(tim, ScenePlan(theme=theme, scenes=scenes), layout=layout)
            css = html.split("<style>")[1].split("</style>")[0]
            assert css.count("{") == css.count("}"), (tid, layout)
            # every declaration's parens balance too (that is what actually broke)
            for decl in re.findall(r"[;{]\s*([a-z-]+\s*:[^{}]+)", css):
                assert decl.count("(") == decl.count(")"), (tid, layout, decl[:70])


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


def test_row_stagger_for_nested_table_cards():
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition
    theme = Theme(id="mono-ink", tokens=json.loads((Path("../design/tokens/mono-ink.json")).read_text())["tokens"])
    t = Timings.from_durations(["表。", "卡。"], [3.0, 3.0])
    plan = ScenePlan(theme=theme, scenes=[
        {"i": 0, "kind": "table", "slots": {"rows": [{"k": "a", "v": "1"}, {"k": "b", "v": "2"}]}},
        {"i": 1, "kind": "cards", "slots": {"name": "X", "rows": [{"k": "a", "v": "1"}, {"k": "b", "v": "2"}]}}])
    html = render_composition(t, plan)
    # the block entrance excludes the nested .rows container, and each scene gets a per-row tween
    assert ".term,.q,.rows)" in html
    assert html.count('.brow", { opacity: 0, x: -24') == 2   # one per table/cards scene
    # a narrative scene must NOT get the row tween (no .row elements)
    t2 = Timings.from_durations(["陈述。"], [3.0])
    plan2 = ScenePlan(theme=theme, scenes=[{"i": 0, "kind": "statement", "slots": {"headline": "陈述"}}])
    assert '.brow", { opacity: 0, x: -24' not in render_composition(t2, plan2)


# ── V27: diagram kinds — content that renders as graphics, not as a line of text ──

def _scene_slice(html: str, i: int) -> str:
    """One scene's MARKUP only — stop at the next section, or at </section> so the
    trailing <style>/<script> (which repeats every selector) can't inflate counts."""
    a = html.index(f'<section id="scene-{i}"')
    b = html.find(f'<section id="scene-{i + 1}"', a)
    return html[a:b if b > -1 else html.index("</section>", a)]


def _theme():
    import json
    from pathlib import Path
    from monoline.ir.sceneplan import Theme
    return Theme(id="mono-ink", tokens=json.loads(Path("../design/tokens/mono-ink.json").read_text())["tokens"])


def test_every_registered_kind_ships_a_template():
    """KINDS is the contract the planner and Studio both draw from — a kind with no
    partial raises inside Jinja at compose time and fails the whole job."""
    from monoline.compose.engine import _TEMPLATES
    from monoline.ir.sceneplan import KINDS
    for k in KINDS:
        assert (_TEMPLATES / "kinds" / f"{k}.html.j2").exists(), k


def test_planner_extracts_diagrams_from_prose():
    from monoline.pipeline.planner import plan_scenes
    beats = ["开场。",
             "交付链路：需求→设计→开发→测试→上线",
             "这套架构分为网关、计算、存储、监控",
             "落地分三步：①盘点存量 ②试点双周 ③全员推广",
             "效率提升 3 倍→周期砍半→成本降三成",
             "从 0→1 的过程",
             "这个模型包括注意力机制",
             "收尾。"]
    kinds = [s["kind"] for s in plan_scenes(beats)]
    assert kinds[1] == "flow" and kinds[2] == "radial" and kinds[3] == "steps"
    # an arrow chain outranks the single-number stat it would otherwise collapse into
    assert kinds[4] == "flow"
    # …and a bare 0→1 range / a "包括" with nothing enumerated stays prose
    assert kinds[5] == "statement" and kinds[6] in ("note", "statement")
    sc = plan_scenes(beats)
    assert sc[1]["slots"]["title"] == "交付链路"
    assert sc[1]["slots"]["nodes"] == ["需求", "设计", "开发", "测试", "上线"]
    assert sc[2]["slots"]["hub"] == "这套架构" and len(sc[2]["slots"]["nodes"]) == 4
    assert sc[3]["slots"]["steps"] == ["盘点存量", "试点双周", "全员推广"]


def test_diagram_scenes_render_nodes_and_suppress_the_caption():
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan
    from monoline.compose.engine import render_composition
    t = Timings.from_durations(["流程。", "架构。", "步骤。"], [4.0, 4.0, 4.0])
    plan = ScenePlan(theme=_theme(), scenes=[
        {"i": 0, "kind": "flow", "slots": {"title": "链路", "nodes": ["A", "B", "C"], "verbatim": True}},
        {"i": 1, "kind": "radial", "slots": {"hub": "平台", "nodes": ["网关", "计算", "存储"], "verbatim": True}},
        {"i": 2, "kind": "steps", "slots": {"title": "节奏", "steps": ["盘存量", "试双周", "全推广"], "verbatim": True}}])
    html = render_composition(t, plan)
    s0, s1, s2 = (_scene_slice(html, i) for i in range(3))
    assert s0.count('class="node') == 3 and s0.count('class="link"') == 2      # nodes + arrows
    assert s1.count('class="node') == 4 and s1.count('class="spoke"') == 3     # hub + branches + spokes
    assert s2.count('class="node') == 3 and s2.count("rail-fill") == 1         # pills + progress rail
    # the node labels ARE the sentence, so no caption box on top of them
    assert '<div class="cap">' not in s0 + s1 + s2
    # diagrams get their own assembly choreography instead of the generic block entrance
    assert "#scene-0 .node" in html and "#scene-1 .node" in html
    assert "#scene-0 .inner > *:not(" not in html
    # branch anchors come from compose-time math, not from the DOM
    assert 'left:18%; top:32.0%' in s1 and 'left:82%; top:50.0%' in s1


def test_segmenter_frees_a_colon_introduced_arrow_chain():
    from monoline.pipeline.planner import plan_scenes
    from monoline.pipeline.segment import segment_text
    fused = "现代团队做产品，靠的是一条清晰的链路：需求→设计→开发→测试→上线。"
    assert segment_text(fused) == ["现代团队做产品，靠的是一条清晰的链路", "需求→设计→开发→测试→上线。"]
    # …and the freed tail is readable as a flow, which the fused beat could never be
    assert plan_scenes(["开场。", "需求→设计→开发→测试→上线", "收尾。"])[1]["kind"] == "flow"
    # k:v lines must NOT split — the table planner reads them as one beat
    assert segment_text("命中：68%；覆盖：42%") == ["命中：68%；覆盖：42%"]


def test_radial_reflows_for_portrait_without_overflow():
    from monoline.ir.sceneplan import Canvas
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan
    from monoline.compose.engine import render_composition
    plan = ScenePlan(theme=_theme(), canvas=Canvas(width=1080, height=1920), scenes=[
        {"i": 0, "kind": "radial", "slots": {"hub": "平台", "nodes": ["网关", "计算", "存储"], "verbatim": True}}])
    html = render_composition(Timings.from_durations(["架构。"], [4.0]), plan)
    assert 'data-aspect="portrait"' in html
    # two side columns don't fit 9:16 — the branches fan down the page instead
    assert 'left:18%' not in html and 'left:50%; top:13%' in html
    assert 'left:66%' in html and 'left:34%' in html


# ── V28: Mandarin tones ─────────────────────────────────────────────────────────

def test_zh_phonemizer_carries_lexical_tones():
    """The bug this locks out: kokoro-onnx phonemizes zh with espeak, which writes tones
    as digits; Kokoro's 114-symbol vocab has no digits and drops them silently, so
    妈/马/骂 reached the model as one identical string and every zh voice sounded
    toneless ("dialect"). Tone contours must survive to the model."""
    import pytest
    from monoline import tts_zh
    pytest.importorskip("misaki")
    from kokoro_onnx.config import DEFAULT_VOCAB

    tones = [tts_zh.phonemize(s) for s in "妈麻马骂"]
    assert len(set(tones)) == 4, tones
    assert all(any(a in t for a in "→↗↓↘") for t in tones), tones
    assert not [c for t in tones for c in t if c not in DEFAULT_VOCAB]   # nothing dropped
    assert tts_zh.phonemize("师") == tts_zh.phonemize("诗")               # real homophones
    assert "ʂ" in tts_zh.phonemize("诗")                                 # retroflex initial kept
    assert "pei" in tts_zh.phonemize("提升3倍")                           # digits read in Chinese
    assert "," in tts_zh.phonemize("需求→设计→开发")                       # diagram glyph = pause
    assert "P" not in tts_zh.phonemize("API")                             # Latin via en-us


# ── V29: connected model — target detection + weak-beat storyboard upgrade ──────

def _fake_httpx(monkeypatch, payload_for):
    import httpx
    from monoline.llm import client as llm_client

    class _Resp:
        def __init__(self, data, code=200):
            self._d, self.status_code = data, code

        def json(self):
            return self._d

        def raise_for_status(self):
            return None

        @property
        def text(self):
            return str(self._d)

    def _get(url, **kw):
        return _Resp(payload_for("get", url))

    monkeypatch.setattr(llm_client.httpx, "get", _get)
    monkeypatch.setattr(httpx, "get", _get)
    monkeypatch.setattr(llm_client, "_CACHE", None)


def test_llm_target_auto_detects_local_ollama(monkeypatch):
    from monoline.llm import client as llm_client
    from monoline.settings import Settings
    _fake_httpx(monkeypatch, lambda kind, url: {"models": [{"model": "batiai/gemma4-e4b:q4"}]})
    s = Settings()
    s.llm_api_key, s.llm_base_url, s.llm_model = "", "https://api.openai.com/v1", "gpt-4o-mini"
    t = llm_client.detect(s, force=True)
    assert t.ok and t.source == "ollama" and t.model == "batiai/gemma4-e4b:q4"
    assert t.base_url.endswith("/v1")
    # unreachable Ollama → not ready, with a reason the UI can show (never an exception)
    _fake_httpx(monkeypatch, lambda kind, url: (_ for _ in ()).throw(OSError("connection refused")))
    monkeypatch.setattr(llm_client, "_CACHE", None)
    t2 = llm_client.detect(s, force=True)
    assert not t2.ok and t2.source == "none" and "connection refused" in t2.detail


def test_llm_upgrade_keeps_rules_where_the_model_is_wrong():
    from monoline.ir.sceneplan import KINDS
    from monoline.llm.planner import ALLOWED, merge
    # every kind we let the model pick must have a registered template
    assert set(ALLOWED) <= set(KINDS), set(ALLOWED) - set(KINDS)
    beats = ["开场白一句。", "需求→设计→开发→测试→上线", "这套平台分为网关、计算、存储三层", "慢就是快。"]
    scenes = [{"i": 0, "kind": "title", "source": "rules:first-line", "slots": {"headline": "开场白"}},
              {"i": 1, "kind": "statement", "source": "rules:default", "slots": {"headline": "需求"}},
              {"i": 2, "kind": "statement", "source": "rules:default", "slots": {"headline": "平台"}},
              {"i": 3, "kind": "summary", "source": "rules:position", "slots": {"headline": "慢就是快"}}]
    payload = {"storyboard": [                      # models wrap arrays in an object shell
        {"i": 1, "kind": "flow", "slots": {"nodes": ["需求", "设计", "开发", "测试", "上线"]}},
        {"i": 2, "kind": "radial", "slots": {"hub": "这套平台", "nodes": ["网关", "计算", "存储"]}},
    ]}
    out, stats = merge(beats, scenes, payload)
    assert len(out) == len(beats)                    # the invariant survives a bad model reply
    assert [s["kind"] for s in out] == ["title", "flow", "radial", "summary"]
    assert out[1]["source"] == "llm:upgrade" and out[1]["slots"]["nodes"][0] == "需求"
    assert stats == {"asked": 2, "upgraded": 2, "rejected": 0}
    # invented copy, illegal kind, and a dropped beat are all refused, beat by beat
    bad = [{"i": 1, "kind": "flow", "slots": {"nodes": ["需求", "融资", "上线"]}},      # 融资 not in beat
           {"i": 2, "kind": "mindmap", "slots": {"hub": "平台", "nodes": ["网关", "计算"]}}]  # no such kind
    out2, st2 = merge(beats, scenes, bad)
    assert [s["kind"] for s in out2] == ["title", "statement", "statement", "summary"]
    assert st2 == {"asked": 2, "upgraded": 0, "rejected": 2}
    # a short-but-not-grounded value ("3倍" vs "3 倍") still counts as grounded after punctuation folds
    ok = [{"i": 1, "kind": "stat", "slots": {"value": "3倍", "label": "需求"}}]
    out3, st3 = merge(["开场。", "需求 3 倍完成"], [{"i": 0, "kind": "title", "slots": {}},
                                                   {"i": 1, "kind": "statement", "slots": {}}], ok)
    assert out3[1]["kind"] == "stat" and st3["upgraded"] == 1
    # grounded but cut mid-sentence ("…的核心是") is a truncation bug on screen → refuse it
    tail = [{"i": 1, "kind": "definition", "slots": {"term": "确定性渲染", "gloss": "这个工具的核心是"}}]
    out4, st4 = merge(["开场。", "这个工具的核心是确定性渲染。"],
                      [{"i": 0, "kind": "title", "slots": {}}, {"i": 1, "kind": "statement", "slots": {}}], tail)
    assert out4[1]["kind"] == "statement" and st4["rejected"] == 1


# ── V30: pre-flight brand identity + phase separation ──────────────────────────

def test_brand_store_round_trip_and_freeze(tmp_path):
    import pathlib
    import pytest
    from monoline import brand
    from monoline.settings import Settings
    s = Settings()
    s.__dict__["app_dir"] = tmp_path          # isolate: never touch the real app dir
    assert brand.load(s)["label"] == "Monoline" and brand.load(s)["logo"] == ""
    # dropping with nothing stored must not resolve Path("") to the cwd and unlink it
    assert brand.drop_logo(s)["logo"] == ""
    png = pathlib.Path("src/monoline/static/favicon.png").read_bytes()
    assert brand.put_logo(s, png, ".png")["logo"].startswith("logo-")
    assert brand.put_logo(s, png + b"1", ".png")["logo"].startswith("logo-")
    assert len(list((tmp_path / "brand").glob("logo-*"))) == 1   # the old one is gone
    name = brand.load(s)["logo"]
    assert brand.save(s, label="Acme", accent="#FF7A5A")["label"] == "Acme"
    cfg = brand.apply_to_config(s, {"voice": "zf_xiaoxiao"})
    assert cfg["brand"] == "Acme" and cfg["accent"] == "#FF7A5A" and cfg["logo"] == name
    rel = brand.freeze_logo_into(s, "j1", name)
    assert rel == f"assets/{name}" and (tmp_path / "workspaces/j1/composition" / rel).is_file()
    assert brand.freeze_logo_into(s, "j2", "../escape.png") == ""      # no traversal
    with pytest.raises(ValueError):
        brand.put_logo(s, b"x" * 10, ".exe")


def test_spa_index_is_not_cacheable():
    """A cached index.html pins the whole app to an old bundle — the reported
    'clicked generate, nothing happened'."""
    from monoline.api.app import SpaStatic
    assert SpaStatic.__doc__ and "never be cached" in SpaStatic.__doc__


def test_narration_stops_spelling_punctuation_aloud():
    """Measured before the fix: a bare % reached the model as "percent" and ** as
    "asterisk asterisk", because non-CJK runs go through an English G2P."""
    from monoline import narration
    assert narration.clean("覆盖率 92%。") == "覆盖率 92%。"          # numbers stay, they read as 百分之…
    assert "%" not in narration.clean("命中率 %。")                  # a stray % is not a word
    for tok in ("*", "_", "~", "`", "#", "|", "→", "😂"):
        assert tok not in narration.clean(f"甲{tok}乙")
    assert narration.clean("需求→设计→开发") == "需求，设计，开发"
    assert narration.clean("慢——真的很慢") .endswith("慢")
    assert "……" in narration.clean("等等……再说明白")
    # rate is bounded inside what the synth accepts, and it differentiates line shapes
    assert 0.5 <= narration.rate("") <= 2.0
    assert narration.rate("效率提升 3 倍。") < narration.rate("这是一句明显超过三十四个字的很长的旁白句子用来验证长句会略微加快的行为")


def test_phrasing_splits_on_breaths():
    from monoline import tts_zh
    parts = tts_zh._phrasing("深海会发光，这不是反射阳光，而是体内的化学反应。")
    assert [k for _, k in parts] == ["clause", "clause", "sentence"]
    long_gap = tts_zh._phrasing("它更亮……也更容易被看见。")
    assert "long" in [k for _, k in long_gap]


# ── V30f: arch / cycle / funnel ─────────────────────────────────────────────────

def test_planner_sees_a_stack_a_ring_and_a_funnel():
    from monoline.pipeline.planner import plan_scenes
    def kind_of(b):
        return plan_scenes(["开场。", b, "收尾。"])[1]
    f = kind_of("漏斗：曝光 12000 人、点击 3400 人、下单 520 人、复购 90 人")
    assert f["kind"] == "funnel" and f["slots"]["title"] == "漏斗"
    assert f["slots"]["stages"][0] == {"k": "曝光", "v": "12000 人"}
    c = kind_of("增长飞轮：内容→流量→信任→更多内容")
    assert c["kind"] == "cycle" and c["slots"]["nodes"] == ["内容", "流量", "信任"]   # loop closes, dup dropped
    a = kind_of("这套平台分为接入层、服务层、存储层三层")
    assert a["kind"] == "arch" and a["slots"]["layers"] == ["接入层", "服务层", "存储层"]
    # an open chain is still a line, and a non-monotone percent set is a comparison
    # of three unrelated rates — a bar chart, not a table (V31d) and not a funnel.
    assert kind_of("需求→设计→开发→测试→上线")["kind"] == "flow"
    assert kind_of("命中率：68%，覆盖率：42%，准确率：91%")["kind"] == "bars"


def test_new_diagram_kinds_render_their_shapes():
    from monoline.ir.sceneplan import DIAGRAM_KINDS, KINDS, ScenePlan
    from monoline.ir.timings import Timings
    from monoline.compose.engine import render_composition
    from monoline.compose.templates.kinds import __init__ as _  # noqa: F401
    assert {"arch", "cycle", "funnel"} <= set(KINDS) <= set(DIAGRAM_KINDS | set(KINDS))
    for k in ("arch", "cycle", "funnel"):
        assert k in DIAGRAM_KINDS, k
    t = Timings.from_durations(["层。", "环。", "漏斗。"], [4.0, 4.0, 4.0])
    plan = ScenePlan(theme=_theme(), scenes=[
        {"i": 0, "kind": "arch", "slots": {"title": "平台", "layers": ["接入层", "服务层", "存储层"], "verbatim": True}},
        {"i": 1, "kind": "cycle", "slots": {"title": "增长", "nodes": ["内容", "流量", "信任"], "verbatim": True}},
        {"i": 2, "kind": "funnel", "slots": {"title": "转化", "stages": [{"k": "曝光", "v": "12000"}, {"k": "点击", "v": "3400"}, {"k": "下单", "v": "520"}], "verbatim": True}},
    ])
    html = render_composition(t, plan)
    s0, s1, s2 = (_scene_slice(html, i) for i in range(3))
    assert s0.count('class="layer') == 3 and "width:98.0%" in s0 and "width:60.0%" in s0   # widest at the bottom
    assert s1.count('class="node') == 3 and s1.count('class="arc"') == 3
    # 520/12000 really is 4.3%; the old 26% floor drew it six times too wide
    assert s2.count('class="fbar') == 3 and "width:100.0%" in s2 and "width:28.3%" in s2 and "width:4.3%" in s2
    assert '<div class="cap">' not in s0 + s1 + s2
    assert "#scene-0 .layer" in html and "#scene-1 .arc" in html and "#scene-2 .fbar" in html


def test_funnel_geometry_is_monotone_and_readable():
    from monoline.compose.viz import funnel_widths, polar, stack_widths
    assert funnel_widths(["100%", "50%", "10%"]) == [100.0, 50.0, 10.0]   # linear: half a share, half a bar
    assert funnel_widths(["100%", "50%", "0.1%"]) == [100.0, 50.0, 4.0]   # floored at a visible sliver
    assert all(a >= b for a, b in zip(funnel_widths(["9", "80", "7"]), funnel_widths(["9", "80", "7"])[1:]))
    assert polar(50, 50, 33, -90) == (50.0, 17.0) and polar(50, 50, 33, 0) == (83.0, 50.0)
    assert stack_widths(3) == [60.0, 79.0, 98.0]


def test_last_beat_keeps_its_shape():
    """Position used to win: a funnel that happened to close the script became a summary
    card and the diagram was thrown away."""
    from monoline.pipeline.planner import plan_scenes
    last = plan_scenes(["开场一句。", "中间一句普通的话。", "漏斗：曝光 12000 人、点击 3400 人、下单 520 人。"])[-1]
    assert last["kind"] == "funnel"
    plain = plan_scenes(["开场一句。", "中间一句普通的话。", "所以慢就是快，快就是慢。"])[-1]
    assert plain["kind"] == "summary" and plain["source"] == "rules:position"


def test_a_funnel_only_draws_when_things_shrink():
    """A funnel encodes loss. An increasing enumeration ("2019 100 万、2020 300 万…") is
    growth, and flat-lining it into a funnel would be a lie on screen."""
    from monoline.pipeline.planner import plan_scenes
    growing = plan_scenes(["开场。", "营收：2019 年 100 万、2020 年 300 万、2021 年 900 万", "收尾。"])[1]
    assert growing["kind"] != "funnel"
    shrinking = plan_scenes(["开场。", "漏斗：曝光 12000 人、点击 3400 人、下单 520 人", "收尾。"])[1]
    assert shrinking["kind"] == "funnel"


def test_brand_api_round_trip_including_logo_delete():
    """The DELETE route once fed drop_logo()'s dict into _brand_view(settings) → 500 on
    the Studio's 移除 button. Every brand endpoint is answered through the real app."""
    from fastapi.testclient import TestClient
    from monoline.api.app import app
    c = TestClient(app)
    assert c.patch("/api/brand", json={"label": "Acme", "accent": "#FF7A5A"}).status_code == 200
    assert c.patch("/api/brand", json={"accent": "red"}).status_code == 422
    assert c.patch("/api/brand", json={"theme": "nope"}).status_code == 422
    png = (pathlib.Path(__file__).parent.parent / "src/monoline/static/favicon.png").read_bytes()
    up = c.post("/api/brand/logo", files={"file": ("f.png", png, "image/png")})
    assert up.status_code == 200 and up.json()["logo"].startswith("logo-")
    assert c.get(f"/api/brand/logo?name={up.json()['logo']}").status_code == 200
    assert c.post("/api/brand/logo", files={"file": ("f.exe", b"x", "application/octet-stream")}).status_code == 422
    gone = c.delete("/api/brand/logo")
    assert gone.status_code == 200 and gone.json()["logo"] == ""
    assert c.delete("/api/brand/logo").status_code == 200      # idempotent
    c.patch("/api/brand", json={"label": "Monoline", "accent": ""})


def test_document_metadata_v53():
    """V53: the shell carries real metadata, and the CLI it advertises exists.

    The noscript block is the one place the SPA states a command out loud, so it has to
    name a command that is actually registered — an invented one reads as documentation
    and fails as instructions.
    """
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    html = (root / "web" / "index.html").read_text()
    for tag in ('name="description"', 'name="application-name"', 'property="og:title"',
                'property="og:description"', 'property="og:site_name"', 'name="robots"',
                'name="theme-color"', 'rel="icon"'):
        assert tag in html, f"shell is missing {tag}"
    # the default must agree with the app's default language; i18n rewrites it at runtime
    assert '<html lang="zh-CN"' in html
    assert len(re.search(r'name="description" content="([^"]+)"', html).group(1)) > 40

    cli = (root / "backend" / "src" / "monoline" / "cli.py").read_text()
    registered = set(re.findall(r'@app\.command\("([a-z-]+)"\)', cli)) | \
        set(re.findall(r'@app\.command\(\)\ndef (\w+)', cli))
    for cmd in re.findall(r"<code>monoline ([a-z-]+)", html):
        assert cmd in registered, f"noscript advertises `monoline {cmd}`, not registered in {sorted(registered)}"


def test_rotation_variants_match_the_frontend_registry_v49():
    """Studio's treatment chips and rotation.py's assignment must be the same list.

    The picker writes slots.variant, the template reads it, and rotation decides it
    automatically — three places, one vocabulary. A rename on either side would silently
    leave chips that render nothing.
    """
    import re
    from pathlib import Path
    from monoline.pipeline.rotation import VARIANTS, VARIANT_KINDS
    src = (Path(__file__).resolve().parents[2] / "web" / "src" / "modes.tsx").read_text()
    ids = re.findall(r'\{ id: "([a-z]+)", zh: "([^"]+)" \}', src)
    assert [i for i, _ in ids] == list(VARIANTS), f"chips {[i for i, _ in ids]} != {VARIANTS}"
    assert all(zh.strip() for _, zh in ids), "every treatment needs a Chinese label"
    kinds = re.search(r"export const VARIANT_KINDS = \[([^\]]+)\]", src).group(1)
    assert {k.strip().strip('"') for k in kinds.split(",")} == set(VARIANT_KINDS)
    # and the CSS must carry a rule for every treatment beyond hero, or the chip is a no-op
    css = (Path(__file__).resolve().parents[1] / "src" / "monoline" / "compose"
           / "templates" / "base.html.j2").read_text()
    for v in VARIANTS:
        if v == "hero":
            continue
        assert f".k-statement.v-{v}" in css, f"treatment {v} has no statement rule"


# ── V54a: 长句二次切分时，切点必须是「一屏能收住」的地方 ───────────────────────────
DATE_STUB = "余承东回应问界品牌调整，赛力斯主动提出自己主导，2026年8月26日，两家公司的公告几乎同时发出。"


def test_a_date_stub_never_closes_a_beat_v54a():
    """The old greedy pack cut at 40 chars wherever it landed, so this sentence's first beat
    ended on 「2026年8月26日，」 — a date with no predicate, which the slide then hero-ed as
    if it were a point. Measured over 42 stored scripts: 34 beats ended on a ≤6-char stub."""
    from monoline.pipeline.segment import segment_text
    beats = segment_text(DATE_STUB)
    assert len(beats) == 1, f"the stub was kept as a beat end: {beats}"
    assert beats[0].endswith("。")


def test_bad_cut_predicate_v54a():
    from monoline.pipeline.segment import _bad_cut
    assert _bad_cut("前面有一句完整的话说的是件事，", "而是后面才见分晓。")      # continuation
    assert _bad_cut("赛力斯主动提出自己主导，2026年8月26日，", "两家公司…")      # stub tail
    assert not _bad_cut("赛力斯主动提出自己主导这件事，", "两家公司的公告同时发出。")  # a real clause
    # a lookbehind split leaves an empty tail on a string that ends at the boundary; taking
    # [-1] of that made every cut look like a stub, which is how the first version of this
    # rule packed every beat to the ceiling instead of choosing boundaries.
    assert not _bad_cut("这是一句足够长的话它自己能收住，", "下一句也说得完。")


def test_avoiding_a_bad_cut_still_respects_a_ceiling_v54a():
    """Absorbing forward can't be open-ended: a beat is a slide, and a slide has to fit."""
    from monoline.pipeline.segment import CEIL_FACTOR, SentenceSegmenter
    chain = "，".join(f"第{i}个要点说明一件事" for i in range(12)) + "。"
    beats = SentenceSegmenter().segment(chain)
    assert len(beats) > 1, "a 12-clause chain must still become several beats"
    assert all(SentenceSegmenter()._len(b) <= 40 * CEIL_FACTOR for b in beats[:-1]), beats


def test_no_spring_overshoot_in_entrances_v52a():
    """`back.out` is the #1 turn-off in agent-made motion per HyperFrames' own
    spring-pop-entrance rule ("never a default"), and every theme token already ships
    power3.out for entrances. This is a ratchet: the template had 4 overshoots
    (.node / .hub-mark / .kcard / .donut) and none of them survive."""
    import json
    from pathlib import Path
    from monoline.ir.timings import Timings
    from monoline.ir.sceneplan import ScenePlan, Theme
    from monoline.compose.engine import render_composition

    theme = Theme(id="mono-ink", tokens=json.loads(
        (Path(__file__).parents[2] / "design/tokens/mono-ink.json").read_text())["tokens"])
    scenes = [
        {"i": 0, "kind": "flow", "slots": {"title": "链路", "nodes": ["写稿", "分镜", "出片"]}},
        {"i": 1, "kind": "cycle", "slots": {"title": "循环", "hub": "数据", "nodes": ["采集", "训练", "上线"]}},
        {"i": 2, "kind": "kpi", "slots": {"title": "指标", "cards": [{"label": "成本", "value": "12"}]}},
        {"i": 3, "kind": "share", "slots": {"title": "占比", "total": "100", "parts": [{"label": "A", "value": "60"}]}}]
    html = render_composition(Timings.from_durations([s["kind"] for s in scenes], [4.0] * 4),
                              ScenePlan(theme=theme, scenes=scenes))
    assert "back.out" not in html, f"overshoot crept back in: {[l for l in html.splitlines() if 'back.out' in l]}"
    assert 'ease: "power3.out"' in html


def test_pipeline_stages_match_the_spa_workflow_list_v53():
    """The nine stage keys are a contract: the runner writes them, the API ships them, and
    Studio draws one row per key. It drifted twice (App.tsx carried a stale second copy of
    the list, since deleted), so the Python list is now the owner and the SPA is checked
    against it instead of being trusted to remember."""
    import re
    from pathlib import Path
    from monoline.pipeline.runner import STAGES
    root = Path(__file__).parents[2]
    studio = (root / "web/src/Studio.tsx").read_text()
    listed = re.search(r"const STAGE_ORDER = \[([^\]]*)\]", studio)
    assert listed, "Studio.tsx lost its STAGE_ORDER — the workflow view cannot render"
    keys = [k.strip().strip('"') for k in listed.group(1).split(",") if k.strip()]
    assert keys == list(STAGES), f"SPA workflow order drifted from the pipeline: {keys} vs {STAGES}"
    labels = re.search(r"const STAGE_LABEL[^{]*\{(.*?)\n\};", studio, re.S)
    assert labels, "Studio.tsx lost STAGE_LABEL"
    unlabeled = [k for k in keys if not re.search(rf"\b{k}\s*:", labels.group(1))]
    assert not unlabeled, f"stage rows with no Chinese label would render blank: {unlabeled}"


def test_no_unused_css_classes_in_the_spa_stylesheet_v53():
    """Six selectors survived their markup (.wordmark / .hint / .seg-ms / .result /
    .result-meta / .wms) and nobody noticed, because no gate ever looked. A class name is
    considered live if its text appears anywhere in the SPA sources — deliberately generous
    (template-literal-built names like `wrow ${st}` count), because a gate that false-fails
    on dynamic classes gets disabled, and this one only has to catch the never-referenced."""
    import re
    from pathlib import Path
    root = Path(__file__).parents[2]
    css = (root / "web/src/styles.css").read_text()
    sources = "".join(p.read_text() for p in (root / "web/src").glob("*.tsx")) \
        + "".join(p.read_text() for p in (root / "web/src").glob("*.ts")) \
        + (root / "web/index.html").read_text()
    dead = sorted({c for c in re.findall(r"\.([A-Za-z][\w-]*)", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
                   if c not in sources})
    assert not dead, f"{len(dead)} CSS classes no markup can produce: {dead}"
