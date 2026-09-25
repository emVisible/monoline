import { createElement, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { groupVoices, useAudition, useVoices } from "./voices";

type Scene = { i: number; kind: string; slots: Record<string, any>; source?: string };
type Seg = { i: number; start: number; end: number; norm_duration: number; text: string };
type Stage = { key: string; status: string; duration_ms?: number | null };
type Artifact = { kind: string; size_bytes: number; state: string };
type Job = { id: string; slug: string; title: string; status: string; total_duration: number | null; config_json?: string | null; canvas_json?: string | null; error: string | null };
type Hydration = { job: Job; stages: Stage[]; segments: Seg[]; artifacts: Artifact[]; plan: { scenes: Scene[] } | null; events: any[] };

const KINDS = ["title", "statement", "section", "definition", "stat", "table", "cards", "compare", "quote", "list", "note", "summary", "image", "flow", "radial", "steps", "arch", "cycle", "funnel", "bars", "kpi", "timeline", "share", "trend", "matrix", "poster"];
const STAGE_ORDER = ["script", "tts", "assemble", "plan", "fonts", "compose", "gate", "render", "deliver"];
const STAGE_LABEL: Record<string, string> = {
  script: "切分", tts: "语音合成", assemble: "拼接旁白", plan: "分镜规划", fonts: "字体子集",
  compose: "生成画面", gate: "质检", render: "渲染", deliver: "出片",
};
// scalar slot keys to expose per kind (arrays handled separately)
const SCALAR_SLOTS: Record<string, string[]> = {
  title: ["eyebrow", "headline", "sub"], statement: ["eyebrow", "headline", "sub"], summary: ["eyebrow", "headline"],
  section: ["index", "title"], definition: ["term", "gloss"], stat: ["value", "unit", "label", "delta", "trend"],
  table: ["title"], cards: ["title", "tagline"], quote: ["q", "attr"], list: ["title"], note: ["marker", "body"],
  compare: ["pivot"], image: ["headline"], flow: ["title"], steps: ["title"], radial: ["hub"], arch: ["title"], cycle: ["title"], funnel: ["title"],
  poster: ["tab", "body", "by"],
  bars: ["title"], kpi: ["title"], timeline: ["title"], share: ["title"], trend: ["title"], matrix: ["title", "x_axis", "y_axis"],
};
// kind → the string-array slot its editor exposes (list items / diagram nodes / timeline steps)
const LIST_SLOT: Record<string, string> = { list: "items", flow: "nodes", radial: "nodes", steps: "steps", arch: "layers", cycle: "nodes", trend: "series", matrix: "cells", poster: "hl" };
const LIST_LABEL: Record<string, string> = { list: "列表项", flow: "流程节点", radial: "分支节点", steps: "步骤", arch: "层（自上而下）", cycle: "环上节点", funnel: "漏斗层（自上而下）", trend: "数值序列", matrix: "四个象限（按 01→04 顺序）" };

type IconDef = { name: string; body: string };

function IconGlyph({ body, size = 18 }: { body: string; size?: number }) {
  return createElement("svg", {
    viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor",
    strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true,
    dangerouslySetInnerHTML: { __html: body },
  });
}

/** Searchable grid picker — 158 icons is a wall of text in a <select>. */
function IconPicker({ icons, value, onChange }: { icons: IconDef[]; value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement | null>(null);
  const current = icons.find((i) => i.name === value);
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? icons.filter((i) => i.name.includes(s)) : icons;
  }, [icons, q]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const onDown = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("mousedown", onDown); };
  }, [open]);
  const pick = (v: string) => { onChange(v); setOpen(false); };
  return (
    <div className="icon-pick" ref={box}>
      <button type="button" className="fld icon-trigger" aria-haspopup="listbox" aria-expanded={open}
        onClick={() => setOpen((v) => !v)}>
        {current ? <IconGlyph body={current.body} /> : <span className="icon-dash">—</span>}
        <span className="icon-name">{value || "无图标"}</span>
        <span className="icon-count">{icons.length}</span>
      </button>
      {open && (
        <div className="icon-pop" role="listbox" aria-label="图标库">
          <input className="fld icon-filter" placeholder="筛选图标…" value={q} autoFocus
            onChange={(e) => setQ(e.target.value)} />
          <div className="icon-grid">
            <button type="button" role="option" aria-selected={!value}
              className={`icon-cell clear${!value ? " on" : ""}`} onClick={() => pick("")}>无</button>
            {shown.map((i) => (
              <button key={i.name} type="button" role="option" aria-selected={i.name === value} title={i.name}
                className={`icon-cell${i.name === value ? " on" : ""}`} onClick={() => pick(i.name)}>
                <IconGlyph body={i.body} size={20} />
              </button>
            ))}
          </div>
          {!shown.length && <p className="muted">没有匹配的图标</p>}
        </div>
      )}
    </div>
  );
}

function Player({ src, w, h, registerRef }: { src: string; w: number; h: number; registerRef?: (el: HTMLElement | null) => void }) {
  const ref = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const el = ref.current as any;
    if (el) el.setAttribute("src", src);
  }, [src]);
  useEffect(() => { registerRef?.(ref.current); return () => registerRef?.(null); }, [registerRef]);
  // Audio fix: our composition is static HTML with no HyperFrames runtime, so the
  // player's default "runtime" audio owner never starts the <audio> element → the
  // preview plays silently on desktop (the rendered MP4 is fine). On ready, mirror the
  // composition's audio into a parent-frame proxy (audio-src) and promote the player to
  // "parent" ownership so its play/seek/mute/volume drive an audible, in-sync track.
  useEffect(() => {
    const el = ref.current as any;
    if (!el) return;
    let done = false;
    const promote = () => {
      if (done) return;
      try {
        const f = el.iframeElement || el.shadowRoot?.querySelector("iframe");
        const a = f && f.contentDocument && f.contentDocument.getElementById("vo");
        const url = a && (a.currentSrc || a.src);
        if (url) el.setAttribute("audio-src", url);
        if (typeof el._promoteToParentProxy === "function") { el._promoteToParentProxy(); done = true; }
      } catch { /* player internals unavailable → preview stays silent, never crash */ }
    };
    const onReady = () => promote();
    el.addEventListener("ready", onReady);
    if (el.ready) promote();
    return () => el.removeEventListener("ready", onReady);
  }, [src]);
  // Fit the preview to the job's real aspect ratio: portrait/square are height-bounded
  // (so they don't overflow the stage), landscape/square fill the column width.
  const tall = h > w;
  const style: React.CSSProperties = {
    aspectRatio: `${w} / ${h}`, display: "block", background: "#000", borderRadius: 10,
    ...(tall ? { height: "68vh", width: "auto", maxWidth: "100%", margin: "0 auto" } : { width: "100%", height: "auto" }),
  };
  return createElement("hyperframes-player", { ref, controls: true, style } as any);
}

export function Studio({ data, onBack, onRun, refresh }: { data: Hydration; onBack: () => void; onRun: () => void; refresh?: () => void }) {
  const { job, segments, plan, stages, artifacts, events } = data;
  const scenes = plan?.scenes ?? [];
  const [sel, setSel] = useState(0);
  const [version, setVersion] = useState(1);
  const [draft, setDraft] = useState<Scene | null>(null);
  const debounce = useRef<number | null>(null);
  const narrDebounce = useRef<number | null>(null);
  const moveBeatRef = useRef<(from: number, to: number) => void>(() => {});
  const playerEl = useRef<HTMLElement | null>(null);
  const registerPlayer = useCallback((el: HTMLElement | null) => { playerEl.current = el; }, []);
  const [resynth, setResynth] = useState(false);
  const [bgmBusy, setBgmBusy] = useState(false);
  const [imgBusy, setImgBusy] = useState(false);
  const [reordering, setReordering] = useState(false);
  const [dragI, setDragI] = useState<number | null>(null);
  const [overI, setOverI] = useState<number | null>(null);
  const [themes, setThemes] = useState<{ id: string; label: string; accent: string; paper: string; ink: string }[]>([]);
  const [icons, setIcons] = useState<IconDef[]>([]);
  const [presets, setPresets] = useState<{ id: string; name: string; config: any }[]>([]);
  const [cfg, setCfg] = useState(() => {
    try { const c = JSON.parse(job.config_json || "{}"); return { theme: c.theme || "mono-ink", accent: c.accent || "", brand: c.brand || "Monoline", voice: c.voice || "zf_xiaoxiao", layout: c.layout || "minimal", logo: c.logo || "" }; }
    catch { return { theme: "mono-ink", accent: "", brand: "Monoline", voice: "zf_xiaoxiao", layout: "minimal", logo: "" }; }
  });
  const { voices } = useVoices();
  const audition = useAudition();
  const [voiceBusy, setVoiceBusy] = useState(false);
  const logRef = useRef<HTMLDivElement | null>(null);

  const maxDur = useMemo(() => Math.max(1, ...segments.map((s) => s.norm_duration || 0)), [segments]);
  const byKey = Object.fromEntries(stages.map((s) => [s.key, s]));
  const lastLog: Record<string, string> = {};
  for (const e of events) if (e.message && e.stage) lastLog[e.stage] = e.message;
  const mp4 = artifacts.find((a) => a.kind === "render_mp4");
  const outFmt = (() => { try { return JSON.parse(job.config_json || "{}").format || "mp4"; } catch { return "mp4"; } })();
  const canvas = (() => { try { return JSON.parse(job.canvas_json || "{}"); } catch { return {}; } })();
  const cw = Number(canvas.width) || 1920, ch = Number(canvas.height) || 1080;
  const composed = (byKey["compose"]?.status === "succeeded") || job.status === "succeeded";
  // Phase gate: while a version is being generated the inspector stays out of the way —
  // you watch progress, then adjust once a film exists.
  const generating = job.status === "running";
  const previewSrc = `/w/${job.id}/index.html?v=${version}`;

  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [events.length]);
  useEffect(() => { setDraft(scenes[sel] ?? null); }, [sel, plan]);
  // Keyboard beat navigation (pro-tool): ←/→ or j/k step, Home/End jump, 1–9 index.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      const n = segments.length;
      if (!n) return;
      // Shift+←/→ reorders the selected beat (keyboard-accessible version of drag).
      if (e.shiftKey && (e.key === "ArrowRight" || e.key === "ArrowLeft")) {
        const to = sel + (e.key === "ArrowRight" ? 1 : -1);
        if (to >= 0 && to < n) { moveBeatRef.current(sel, to); e.preventDefault(); }
        return;
      }
      const go = (i: number) => { setSel(Math.max(0, Math.min(n - 1, i))); e.preventDefault(); };
      if (e.key === "ArrowRight" || e.key === "j") go(sel + 1);
      else if (e.key === "ArrowLeft" || e.key === "k") go(sel - 1);
      else if (e.key === "Home") go(0);
      else if (e.key === "End") go(n - 1);
      else if (/^[1-9]$/.test(e.key)) go(parseInt(e.key, 10) - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sel, segments.length]);
  useEffect(() => {
    document.querySelector(".beat.on")?.scrollIntoView({ block: "nearest" });
  }, [sel]);
  // Beat selection drives the preview: seek the player to the chosen beat, offset
  // past the ~0.5s incoming transition so it lands on settled content, not a fade.
  useEffect(() => {
    const el = playerEl.current as any;
    const seg = segments[sel];
    if (!el || typeof el.seek !== "function" || !seg) return;
    const start = Number(seg.start) || 0;
    const end = Number(seg.end) || start + 1;
    const t = Math.min(start + 0.6, Math.max(start, end - 0.05));
    const id = window.setTimeout(() => { try { el.seek(t); } catch { /* not ready yet */ } }, 120);
    return () => window.clearTimeout(id);
  }, [sel, segments, version, composed]);
  useEffect(() => {
    fetch("/api/themes").then((r) => r.json()).then((d) => setThemes(d.themes || [])).catch(() => {});
    fetch("/api/icons").then((r) => r.json()).then((d) => setIcons(d.icons || [])).catch(() => {});
    fetch("/api/presets").then((r) => r.json()).then((d) => setPresets(d.presets || [])).catch(() => {});
  }, []);

  const applyConfig = async (patch: Record<string, string>) => {
    setCfg((c) => ({ ...c, ...patch }));
    const r = await fetch(`/api/jobs/${job.id}/config`, {
      method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(patch),
    });
    if (r.ok) { const d = await r.json(); setVersion(typeof d.version === "number" ? d.version : version + 1); }
  };
  const savePreset = async () => {
    const name = window.prompt("预设名称");
    if (!name) return;
    const r = await fetch("/api/presets", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, config: { theme: cfg.theme, accent: cfg.accent, brand: cfg.brand } }),
    });
    if (r.ok) { const d = await r.json(); setPresets((p) => [{ id: d.id, name, config: cfg }, ...p]); }
  };
  const loadPreset = async (pid: string) => {
    const pr = presets.find((p) => p.id === pid); if (!pr) return;
    const patch: Record<string, string> = {};
    if (pr.config.theme) patch.theme = pr.config.theme;
    if (pr.config.brand) patch.brand = pr.config.brand;
    patch.accent = pr.config.accent || "";
    await applyConfig(patch);
  };

  const changeVoice = async (vid: string) => {
    const prev = cfg.voice;
    if (vid === prev) return;
    setCfg((c) => ({ ...c, voice: vid }));
    setVoiceBusy(true);
    try {
      const r = await fetch(`/api/jobs/${job.id}/voice`, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ voice: vid }),
      });
      if (r.ok) { const d = await r.json(); setVersion(typeof d.version === "number" ? d.version : version + 1); refresh?.(); }
      else setCfg((c) => ({ ...c, voice: prev }));
    } catch {
      setCfg((c) => ({ ...c, voice: prev }));
    } finally {
      setVoiceBusy(false);
    }
  };

  const saveScene = (next: Scene) => {
    setDraft(next);
    if (debounce.current) window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(async () => {
      const r = await fetch(`/api/jobs/${job.id}/plan/scenes/${next.i}`, {
        method: "PATCH", headers: { "content-type": "application/json" },
        body: JSON.stringify({ kind: next.kind, slots: next.slots }),
      });
      if (r.ok) { const d = await r.json(); setVersion(typeof d.version === "number" ? d.version : version + 1); }
    }, 500);
  };

  const setSlot = (key: string, val: any) => draft && saveScene({ ...draft, slots: { ...draft.slots, [key]: val } });
  const setRows = (rows: { k: string; v: string }[]) =>
    draft && saveScene({ ...draft, slots: { ...draft.slots, ...(draft.slots.stages ? { stages: rows } : { rows }) } });
  const setCompare = (side: "a" | "b", key: string, val: string) =>
    draft && saveScene({ ...draft, slots: { ...draft.slots, [side]: { ...(draft.slots[side] || {}), [key]: val } } });

  // Switching kind must seed the new kind's required array/object slots, else the
  // rows/items/compare editors never appear and the scene renders empty.
  const changeKind = (kind: string) => {
    if (!draft) return;
    const slots = { ...draft.slots };
    const pairKey = kind === "funnel" ? "stages" : "rows";
    if ((kind === "table" || kind === "cards" || kind === "bars" || kind === "kpi" || kind === "timeline"
         || kind === "share" || kind === "funnel") && !Array.isArray(slots[pairKey])) {
      slots[pairKey] = [{ k: "", v: "" }, { k: "", v: "" }];
    }
    if (kind === "trend" && !Array.isArray(slots.series)) slots.series = ["", "", ""];
    if (kind === "matrix" && !Array.isArray(slots.cells)) slots.cells = ["", "", "", ""];
    if (kind === "list" && !Array.isArray(slots.items)) slots.items = ["", "", ""];
    if ((kind === "flow" || kind === "radial") && !Array.isArray(slots.nodes)) slots.nodes = ["", "", ""];
    if (kind === "steps" && !Array.isArray(slots.steps)) slots.steps = ["", "", ""];
    if (kind === "arch" && !Array.isArray(slots.layers)) slots.layers = ["", "", ""];
    if (kind === "cycle" && !Array.isArray(slots.nodes)) slots.nodes = ["", "", ""];
    if (kind === "funnel" && !Array.isArray(slots.stages)) slots.stages = [{ k: "", v: "" }, { k: "", v: "" }, { k: "", v: "" }];
    if (kind === "compare") { if (!slots.a) slots.a = { h: "", d: "" }; if (!slots.b) slots.b = { h: "", d: "" }; }
    saveScene({ ...draft, kind, slots });
  };

  const saveNarration = (idx: number, text: string) => {
    if (narrDebounce.current) window.clearTimeout(narrDebounce.current);
    setResynth(true);
    narrDebounce.current = window.setTimeout(async () => {
      try {
        const r = await fetch(`/api/jobs/${job.id}/segments/${idx}`, {
          method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }),
        });
        if (r.ok) { const d = await r.json(); setVersion(typeof d.version === "number" ? d.version : version + 1); }
      } finally {
        setResynth(false);
      }
    }, 1200);
  };

  const uploadBgm = async (file: File) => {
    setBgmBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch(`/api/jobs/${job.id}/bgm`, { method: "POST", body: fd });
      if (r.ok) { const d = await r.json(); setVersion(typeof d.version === "number" ? d.version : version + 1); }
    } finally {
      setBgmBusy(false);
    }
  };

  const uploadImage = async (file: File) => {
    setImgBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch(`/api/jobs/${job.id}/assets`, { method: "POST", body: fd });
      if (r.ok) { const d = await r.json(); setSlot("image", d.rel); }
    } finally {
      setImgBusy(false);
    }
  };

  const moveBeat = async (from: number, to: number) => {
    if (from === to) return;
    const idx = segments.map((_, k) => k);
    const [moved] = idx.splice(from, 1);
    idx.splice(to, 0, moved);
    setReordering(true);
    try {
      const r = await fetch(`/api/jobs/${job.id}/reorder`, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ order: idx }),
      });
      if (r.ok) { const d = await r.json(); setVersion(typeof d.version === "number" ? d.version : version + 1); setSel(to); refresh?.(); }
    } finally {
      setReordering(false);
    }
  };
  moveBeatRef.current = moveBeat;

  const d = draft;

  return (
    <div className="studio3">
      <div className="s3-head">
        <button className="back" onClick={onBack}>← new</button>
        <span className="s3-title">{job.title || "untitled"}</span>
        <span className={`s3-status ${job.status}`} role="status" aria-live="polite">{job.status}</span>
      </div>

      <div className="s3-body">
        {/* left: beats */}
        <aside className="s3-beats" aria-label="节拍列表">
          {segments.map((s) => (
            <button key={s.i}
              className={`beat ${sel === s.i ? "on" : ""} ${dragI === s.i ? "dragging" : ""} ${overI === s.i && dragI !== null && dragI !== s.i ? "dropover" : ""}`}
              draggable={!reordering}
              onClick={() => setSel(s.i)}
              onDragStart={(e) => { setDragI(s.i); e.dataTransfer.effectAllowed = "move"; }}
              onDragOver={(e) => { e.preventDefault(); if (dragI !== null && dragI !== s.i) setOverI(s.i); }}
              onDragLeave={() => setOverI((o) => (o === s.i ? null : o))}
              onDrop={(e) => { e.preventDefault(); if (dragI !== null) moveBeat(dragI, s.i); setDragI(null); setOverI(null); }}
              onDragEnd={() => { setDragI(null); setOverI(null); }}>
              <span className="beat-grip" aria-hidden>⠿</span>
              <span className="beat-i">{s.i + 1}</span>
              <span className="beat-bar" style={{ width: `${((s.norm_duration || 0) / maxDur) * 100}%` }} />
              <span className="beat-txt">{s.text}</span>
              <span className="beat-kind">{scenes[s.i]?.kind || "—"}</span>
            </button>
          ))}
          {reordering && <div className="beats-reorder">重排中…</div>}
          <div className="beats-hint">← → 选拍 · ⇧←/→ 或拖动重排</div>
        </aside>

        {/* center: player + workflow */}
        <main className="s3-stage">
          {composed ? (
            <div className="player-wrap"><Player src={previewSrc} w={cw} h={ch} registerRef={registerPlayer} /></div>
          ) : (
            <div className="player-empty">
              <div className="workflow" aria-live="polite">
                {STAGE_ORDER.map((k) => {
                  const st = byKey[k]?.status || "pending";
                  return (
                    <div key={k} className={`wrow ${st}`}>
                      <span className="seg-dot" /><span className="wname">{STAGE_LABEL[k]}</span>
                      <span className="wlog">{st === "running" ? (lastLog[k] || "进行中…") : (st === "succeeded" ? (lastLog[k] || "") : "")}</span>
                    </div>
                  );
                })}
              </div>
              <div className="log" ref={logRef} role="log" aria-live="polite">{events.slice(-30).map((e) => (
                <div key={e.id} className={`line ${e.level === "error" ? "err" : ""}`}><span className="lstage">{STAGE_LABEL[e.stage] || e.stage || ""}</span><span>{e.message}</span></div>
              ))}</div>
            </div>
          )}
          {job.status === "failed" && (
            <div className="err-banner" role="alert">
              <strong>作业失败</strong>
              <span>{job.error || "见下方日志"}</span>
            </div>
          )}
          <div className="s3-actions">
            {mp4 && job.status === "succeeded" ? (
              <a className="download" href={`/api/jobs/${job.id}/download`} download>Download {outFmt.toUpperCase()} ↓</a>
            ) : (
              <button className="generate" onClick={onRun} disabled={job.status === "running"}>
                {job.status === "running" ? "渲染中…" : "Render →"}
              </button>
            )}
            {composed && segments.length > 0 && (
              <span className="sub-links">
                <a className="ghost sm" href={`/api/jobs/${job.id}/subtitles?fmt=srt`} download title="下载字幕 (SRT)">字幕 SRT</a>
                <a className="ghost sm" href={`/api/jobs/${job.id}/subtitles?fmt=vtt`} download title="下载字幕 (WebVTT)">VTT</a>
                {mp4 && job.status === "succeeded" && (
                  <a className="ghost sm" href={`/api/jobs/${job.id}/poster`} download title="下载封面 (JPG)">封面</a>
                )}
              </span>
            )}
            {job.status === "running" && (
              <button className="ghost" onClick={() => fetch(`/api/jobs/${job.id}/cancel`, { method: "POST" })}>取消</button>
            )}
            <label className="ghost file">
              {bgmBusy ? "载入中…" : "背景音乐"}
              <input type="file" accept="audio/*" hidden disabled={bgmBusy}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadBgm(f); e.target.value = ""; }} />
            </label>
            {composed && <span className="s3-hint">编辑右侧即时更新预览；点 Render 出片</span>}
          </div>
        </main>

        {/* right: inspector */}
        <aside className="s3-inspector" aria-label="属性面板">
          {generating ? (
            <div className="insp-wait" role="status">
              <span className="iw-spin" aria-hidden="true" />
              <div className="iw-title">生成中…</div>
              <p>配置与逐拍编辑会在这一版出片后出现。<b>先生成，再调整</b>——左边阶段流就是当前进度。</p>
            </div>
          ) : (<>
          <div className="appearance">
            <div className="ap-title">外观</div>
            <div className="swatches">
              {themes.map((t) => (
                <button key={t.id} className={`swatch ${cfg.theme === t.id ? "on" : ""}`} aria-pressed={cfg.theme === t.id} title={t.label}
                  style={{ background: t.paper }} onClick={() => applyConfig({ theme: t.id })}>
                  <span className="sw-ink" style={{ background: t.ink }} /><span className="sw-dot" style={{ background: t.accent }} />
                </button>
              ))}
            </div>
            <div className="ap-row">
              <label className="fld-lbl">版式</label>
              <div className="chips">
                {[["minimal", "极简"], ["editorial", "杂志"], ["bold", "醒目"]].map(([v, l]) => (
                  <button key={v} className={cfg.layout === v ? "chip on" : "chip"} aria-pressed={cfg.layout === v} onClick={() => applyConfig({ layout: v })}>{l}</button>
                ))}
              </div>
            </div>
            <div className="ap-row">
              <label className="fld-lbl">品牌</label>
              <input className="fld" defaultValue={cfg.brand} onBlur={(e) => e.target.value !== cfg.brand && applyConfig({ brand: e.target.value })} />
            </div>
            <div className="ap-row">
              <label className="fld-lbl">Logo</label>
              <label className="ghost sm file-btn">上传
                <input type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={async (e) => {
                  const f = e.target.files?.[0]; if (!f) return;
                  const fd = new FormData(); fd.append("file", f);
                  const r = await fetch(`/api/jobs/${job.id}/logo`, { method: "POST", body: fd });
                  if (r.ok) { const d = await r.json(); setCfg((c) => ({ ...c, logo: d.logo })); setVersion(typeof d.version === "number" ? d.version : version + 1); }
                }} />
              </label>
              {cfg.logo ? <button className="ghost sm" onClick={async () => {
                const r = await fetch(`/api/jobs/${job.id}/logo`, { method: "DELETE" });
                if (r.ok) { const d = await r.json(); setCfg((c) => ({ ...c, logo: "" })); setVersion(typeof d.version === "number" ? d.version : version + 1); }
              }}>移除</button> : <span className="muted sm">品牌锁定处显示</span>}
            </div>
            <div className="ap-row">
              <label className="fld-lbl">强调色</label>
              <input type="color" className="accent-pick" value={/^#[0-9a-fA-F]{6}$/.test(cfg.accent) ? cfg.accent : "#C4F82A"}
                onChange={(e) => applyConfig({ accent: e.target.value })} />
              {cfg.accent && <button className="ghost sm" onClick={() => applyConfig({ accent: "" })}>默认</button>}
            </div>
            <div className="ap-row preset-row">
              <select className="fld" value="" onChange={(e) => { if (e.target.value) loadPreset(e.target.value); }}>
                <option value="">载入预设…</option>
                {presets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <button className="ghost sm" onClick={savePreset}>保存</button>
            </div>
          </div>
          {voices.length > 0 && (
            <div className="appearance">
              <div className="ap-title">配音</div>
              <div className="ap-row">
                <label className="fld-lbl">音色{voiceBusy && <span className="resynth-tag"> · 重合成中…</span>}</label>
                <div className="voice-edit">
                  <select className="fld" value={cfg.voice} disabled={voiceBusy} onChange={(e) => changeVoice(e.target.value)}>
                    {groupVoices(voices).map((g) => (
                      <optgroup key={g.name} label={g.name}>
                        {g.items.map((v) => <option key={v.id} value={v.id}>{v.label} · {v.lang}</option>)}
                      </optgroup>
                    ))}
                  </select>
                  <button className={`ghost vaudition ${audition.playingId === cfg.voice ? "playing" : ""}`}
                    onClick={() => audition.toggle(cfg.voice)} disabled={voiceBusy} aria-label="试听当前音色" title="试听">
                    {audition.loadingId === cfg.voice ? <span className="vload" />
                      : audition.playingId === cfg.voice ? <span className="veq"><i /><i /><i /></span>
                      : <span className="vplay" />}
                  </button>
                </div>
                {voiceBusy && <p className="voice-busy-note">逐拍重新合成中（约 {Math.max(2, segments.length * 3)} 秒）…</p>}
              </div>
            </div>
          )}
          {!d ? <p className="muted">选左侧一拍</p> : (
            <>
              <div className="fld-row">
                <label className="fld-lbl">旁白{resynth && <span className="resynth-tag"> · 重合成中…</span>}</label>
                <textarea className="fld narration" key={`n-${sel}`} rows={3}
                  defaultValue={segments[sel]?.text ?? ""}
                  onChange={(e) => saveNarration(sel, e.target.value)} />
              </div>
              <label className="fld-lbl">类型</label>
              <select className="fld" value={d.kind} onChange={(e) => changeKind(e.target.value)}>
                {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
              <p className="src-badge">{scenes[sel]?.source || "manual"}</p>
              <label className="fld-lbl">图标</label>
              <IconPicker icons={icons} value={d.slots.icon ?? ""} onChange={(v) => setSlot("icon", v)} />
              <label className="fld-lbl">{d.kind === "image" ? "图片" : "配图"}</label>
              <div className="img-row">
                {d.slots.image ? (
                  <img className="img-thumb" src={`/w/${job.id}/${d.slots.image}`} alt="" />
                ) : (
                  <span className="img-none">未设置</span>
                )}
                <label className="ghost file">
                  {imgBusy ? "载入中…" : d.slots.image ? "更换" : "上传"}
                  <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden disabled={imgBusy}
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadImage(f); e.target.value = ""; }} />
                </label>
                {d.slots.image && <button className="ghost" onClick={() => setSlot("image", "")}>移除</button>}
              </div>
              {d.slots.image && (
                <div className="fld-row">
                  <label className="fld-lbl">{d.kind === "image" ? "图注" : "配图说明"}</label>
                  <input className="fld" value={d.slots.image_caption ?? ""} onChange={(e) => setSlot("image_caption", e.target.value)} />
                </div>
              )}
              {d.slots.image && (
                <div className="fld-row">
                  <label className="fld-lbl">图片色调</label>
                  <div className="chips" role="group" aria-label="图片色调">
                    <button className={`chip${d.slots.image_tone !== "color" ? " on" : ""}`} aria-pressed={d.slots.image_tone !== "color"}
                      onClick={() => setSlot("image_tone", "mono")}>统一灰调</button>
                    <button className={`chip${d.slots.image_tone === "color" ? " on" : ""}`} aria-pressed={d.slots.image_tone === "color"}
                      onClick={() => setSlot("image_tone", "color")}>保留原色</button>
                  </div>
                </div>
              )}

              {(SCALAR_SLOTS[d.kind] || []).map((key) => (
                <div key={key} className="fld-row">
                  <label className="fld-lbl">{key}</label>
                  <input className="fld" value={d.slots[key] ?? ""} onChange={(e) => setSlot(key, e.target.value)} />
                </div>
              ))}

              {(d.slots.rows || d.slots.stages) && (
                <div className="rows-edit">
                  <label className="fld-lbl">{d.slots.stages ? "漏斗层" : "数据行"}</label>
                  {(d.slots.rows || d.slots.stages).map((r: any, ri: number) => (
                    <div key={ri} className="row2">
                      <input className="fld" value={r.k} onChange={(e) => { const rows = [...(d.slots.rows || d.slots.stages)]; rows[ri] = { ...r, k: e.target.value }; setRows(rows); }} />
                      <input className="fld" value={r.v} onChange={(e) => { const rows = [...(d.slots.rows || d.slots.stages)]; rows[ri] = { ...r, v: e.target.value }; setRows(rows); }} />
                    </div>
                  ))}
                </div>
              )}

              {LIST_SLOT[d.kind] && Array.isArray(d.slots[LIST_SLOT[d.kind]]) && (
                <div className="rows-edit">
                  <label className="fld-lbl">{LIST_LABEL[d.kind]}</label>
                  {(d.slots[LIST_SLOT[d.kind]] as string[]).map((it: string, ii: number) => {
                    const key = LIST_SLOT[d.kind];
                    return <input key={ii} className="fld" value={it}
                      onChange={(e) => { const arr = [...(d.slots[key] as string[])]; arr[ii] = e.target.value; setSlot(key, arr); }} />;
                  })}
                </div>
              )}

              {d.kind === "compare" && (["a", "b"] as const).map((side) => (
                <div key={side} className="rows-edit">
                  <label className="fld-lbl">{side === "a" ? "A 标题/描述" : "B 标题/描述"}</label>
                  <input className="fld" value={d.slots[side]?.h ?? ""} onChange={(e) => setCompare(side, "h", e.target.value)} />
                  <input className="fld" value={d.slots[side]?.d ?? ""} onChange={(e) => setCompare(side, "d", e.target.value)} />
                </div>
              ))}
            </>
          )}
          </>
          )}
        </aside>
      </div>
    </div>
  );
}
