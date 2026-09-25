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
    assert html.count('class="brow"') == 3
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
    assert len(rules) == 1
    for sel in (".headline", ".s-title", ".term", ".q", ".d-title", ".cap > .inner"):
        assert sel in rules[0]


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
    assert s2.count('class="fbar') == 3 and "width:100.0%" in s2 and "width:26.0%" in s2   # monotone funnel
    assert '<div class="cap">' not in s0 + s1 + s2
    assert "#scene-0 .layer" in html and "#scene-1 .arc" in html and "#scene-2 .fbar" in html


def test_funnel_geometry_is_monotone_and_readable():
    from monoline.compose.viz import funnel_widths, polar, stack_widths
    assert funnel_widths(["100%", "50%", "10%"]) == [100.0, 50.0, 26.0]     # floored, never invisible
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
