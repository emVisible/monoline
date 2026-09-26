import { lang, setLang, t } from "./i18n";
import type { Lang } from "./i18n";
import { useEffect, useRef, useState } from "react";
import { Studio } from "./Studio";
import { ModesView } from "./modes";
import { Logo } from "./Logo";
import { groupVoices, useAudition, useVoices } from "./voices";

type Stage = { key: string; seq: number; status: string; error?: string | null };
type Artifact = { id: string; kind: string; rel_path: string; mime: string; size_bytes: number; state: string };
type Job = { id: string; slug: string; title: string; status: string; total_duration: number | null; error: string | null };
type Ev = { id: number; stage: string | null; kind: string; level: string; message: string | null };
type Hydration = { job: Job; stages: Stage[]; segments: any[]; artifacts: Artifact[]; plan: any | null; events: Ev[] };

// A language name is never translated — the toggle shows the *other* language by its own
// name, which is the whole point of a language switch.
const LANG_NAME: Record<Lang, string> = { zh: "中", en: "EN" };

function useHydration(id: string | null) {
  const [data, setData] = useState<Hydration | null>(null);
  const refreshRef = useRef<() => void>(() => {});
  useEffect(() => {
    if (!id) { setData(null); return; }
    let alive = true;
    let es: EventSource | null = null;
    let poll: number | null = null;
    let debounce: number | null = null;

    const refresh = async () => {
      try {
        const d = await (await fetch(`/api/jobs/${id}`)).json();
        if (!alive) return;
        setData(d);
        const st = d?.job?.status;
        if (st === "succeeded" || st === "failed" || st === "cancelled") {
          es?.close(); es = null;
          if (poll) { clearInterval(poll); poll = null; }
        }
      } catch { /* backend briefly unavailable */ }
    };
    // coalesce bursts of SSE frames into one refetch (~150ms)
    const schedule = () => { if (debounce) return; debounce = window.setTimeout(() => { debounce = null; refresh(); }, 150); };
    const startPolling = () => { if (!poll) poll = window.setInterval(refresh, 1500); };
    refreshRef.current = refresh;

    refresh();
    try {
      es = new EventSource(`/api/jobs/${id}/stream`);
      es.onmessage = (e) => {
        try {
          const o = JSON.parse(e.data);
          if (o.type === "done") { es?.close(); es = null; refresh(); }
          else schedule();
        } catch { /* ignore non-JSON keepalive */ }
      };
      es.onerror = () => { es?.close(); es = null; startPolling(); };  // graceful fallback
    } catch { startPolling(); }

    return () => {
      alive = false;
      if (debounce) clearTimeout(debounce);
      es?.close();
      if (poll) clearInterval(poll);
    };
  }, [id]);
  return { data, refresh: () => refreshRef.current() };
}

// H5: the cut decides where the whole film goes, so it is reviewable before any audio is
// paid for. This panel is that review: every beat, its storyboard kind, its section and its
// share of the runtime — editable in place, and what the run then follows.
type OutlineRow = { i: number; text: string; kind: string; ruleKind?: string;
  source: string; section: string; seconds: number };
// Kinds a beat can be pinned to from its own words. A chart kind needs rows the text may not
// contain, and inventing them would put numbers on screen the script never said — that choice
// stays in Studio, where the slots are editable.
const PINNABLE = ["statement", "section", "title", "quote", "note", "definition", "summary", "split", "poster"];

function OutlinePanel({ data, busy, onBack, onRecut, onConfirm }: {
  data: { entries: OutlineRow[]; sections: string[]; est_seconds: number };
  busy: boolean; onBack: () => void; onRecut: () => void; onConfirm: (rows: OutlineRow[]) => void;
}) {
  const [rows, setRows] = useState<OutlineRow[]>(data.entries.map((e) => ({ ...e, ruleKind: e.kind })));
  const shape = (rs: { text: string; kind: string }[]) => JSON.stringify(rs.map((r) => [r.text, r.kind]));
  const dirty = shape(rows) !== shape(data.entries);
  const total = rows.reduce((a, r) => a + r.seconds, 0);
  const set = (n: number, patch: Partial<OutlineRow>) =>
    setRows((rs) => rs.map((r, i) => (i === n ? { ...r, ...patch } : r)));
  const drop = (n: number) => setRows((rs) => rs.filter((_, i) => i !== n));
  const mergeUp = (n: number) => setRows((rs) =>
    n === 0 ? rs : rs.map((r, i) => (i === n - 1
      // the left line usually ends on a full stop; gluing 「…。，下一句」 onto it is a typo
      ? { ...r, text: `${r.text.replace(/[。．.，,、；;：:]+$/, "")}，${rs[n].text}` } : r))
      .filter((_, i) => i !== n));

  return (
    <div className="intake ol-wrap">
      <div className="ol-head">
        <p className="eyebrow">{t("大纲 · 生成前可改")}</p>
        <p className="ol-sum">
          {rows.length} {t("拍")} · {t("预计")} {total.toFixed(0)}s · {data.sections.length} {t("段")}
          {data.sections.length ? `：${data.sections.join(" / ")}` : ""}
        </p>
      </div>
      <ul className="ol-list" role="list">
        {rows.map((r, n) => (
          <li key={`${n}-${r.i}`} className={"ol-row k-" + r.kind + (r.section && rows[n - 1]?.section !== r.section ? " sec-start" : "")}>
            <span className="ol-no">{String(n + 1).padStart(2, "0")}</span>
            <div className="ol-main">
              <textarea className="ol-text" rows={2} value={r.text} aria-label={t("这一拍的旁白")}
                onChange={(e) => set(n, { text: e.target.value })} />
              <div className="ol-meta">
                <select className="ol-kind" value={r.kind} aria-label={t("这一拍的呈现")}
                  onChange={(e) => set(n, { kind: e.target.value })}>
                  {/* the rule's own verdict stays visible even when it is not a pinnable kind —
                      a select that reads `statement` over a `table` beat would lie */}
                  {Array.from(new Set([r.kind, ...PINNABLE])).map((k) => <option key={k} value={k}>{k}</option>)}
                </select>
                <span className="ol-rule" title={r.source}>
                  {r.ruleKind}{r.kind !== r.ruleKind ? ` → ${r.kind}` : ""}
                </span>
                {r.section && <span className="ol-sec">{r.section}</span>}
                <span className="ol-dur">{r.seconds.toFixed(1)}s</span>
              </div>
            </div>
            <div className="ol-ops">
              <button className="ghost sm" disabled={n === 0} onClick={() => mergeUp(n)}
                aria-label={t("并到上一拍")}>⌃</button>
              <button className="ghost sm" onClick={() => drop(n)} aria-label={t("删掉这拍")}>×</button>
            </div>
          </li>
        ))}
      </ul>
      <div className="ol-foot">
        <button className="ghost" onClick={onBack}>{t("← 返回改文稿")}</button>
        <button className="ghost" onClick={onRecut} disabled={busy}>{busy ? t("切分中…") : t("重新切分")}</button>
        <button className="primary" disabled={busy || !rows.length}
          onClick={() => onConfirm(dirty ? rows : [])}>
          {t("按此大纲生成")}{dirty ? ` · ${t("含我的修改")}` : ""}
        </button>
      </div>
    </div>
  );
}


function NewView({ onCreate }: { onCreate: (id: string) => void }) {
  const [script, setScript] = useState("");
  const [ratio, setRatio] = useState("landscape");
  const [layout, setLayout] = useState("minimal");
  const [quality, setQuality] = useState("looks");
  const [fps, setFps] = useState(30);
  const [format, setFormat] = useState("mp4");
  const [busy, setBusy] = useState(false);
  const [topic, setTopic] = useState("");
  const [tone, setTone] = useState("neutral");
  const [len, setLen] = useState("medium");
  const [llm, setLlm] = useState<{ ready: boolean; source: string; model: string | null; detail: string; latency_ms: number | null }>(
    { ready: false, source: "none", model: null, detail: "", latency_ms: null });
  const [llmBusy, setLlmBusy] = useState(false);
  const [genErr, setGenErr] = useState<string | null>(null);
  // V30: brand identity lives at the user level and is set BEFORE generating.
  const [brand, setBrand] = useState<{ label: string; theme: string; accent: string; logo: string; logo_url: string }>(
    { label: "Monoline", theme: "mono-ink", accent: "", logo: "", logo_url: "" });
  const [themes, setThemes] = useState<{ id: string; label: string; paper: string; ink: string; accent: string }[]>([]);
  const [brandOpen, setBrandOpen] = useState(false);
  const [brandBusy, setBrandBusy] = useState(false);
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const topicRef = useRef<HTMLInputElement | null>(null);
  const [llmPlan, setLlmPlan] = useState(true);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiErr, setAiErr] = useState<string | null>(null);
  const { voices, default: defaultVoice } = useVoices();
  const [voice, setVoice] = useState("");
  const [voiceOpen, setVoiceOpen] = useState(false);
  const audition = useAudition();
  // V47: the beat count is the backend segmenter's answer (POST /api/script/preview), not a
  // local regex. The previous estimate was a second, simpler implementation of segmentation
  // in TypeScript and it disagreed with the real job on 30% of stored scripts — always low,
  // because the clause split and tiny-beat merge only exist in Python (worst case: UI 6,
  // job 17). Debounced; seq drops a response that was superseded while in flight.
  const [count, setCount] = useState<{ beats: number; seconds: number; cap: number; over: boolean } | null>(null);
  const seq = useRef(0);
  useEffect(() => {
    const mine = ++seq.current;
    if (!script.trim()) { setCount(null); return; }
    const id = window.setTimeout(() => {
      fetch("/api/script/preview", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ script }),
      })
        .then((r) => r.json())
        .then((d) => { if (seq.current === mine) setCount({ beats: d.beats, seconds: d.seconds, cap: d.cap, over: !!d.over_cap }); })
        .catch(() => { if (seq.current === mine) setCount(null); });
    }, 350);
    return () => window.clearTimeout(id);
  }, [script]);
  const hasText = script.trim().length > 0;
  const chars = script.replace(/\s/g, "").length;

  const loadLlm = (refresh = false) => {
    setLlmBusy(true);
    fetch("/api/script/status" + (refresh ? "?refresh=1" : ""))
      .then((r) => r.json())
      .then((d) => setLlm({
        ready: !!d.ready, source: d.source || "none", model: d.model || null,
        detail: d.detail || "", latency_ms: typeof d.latency_ms === "number" ? d.latency_ms : null,
      }))
      .catch(() => setLlm({ ready: false, source: "none", model: null, detail: t("无法连接后端"), latency_ms: null }))
      .finally(() => setLlmBusy(false));
  };
  useEffect(() => { loadLlm(false); }, []);
  useEffect(() => {
    fetch("/api/brand").then((r) => r.json()).then((d) => setBrand(d)).catch(() => {});
    fetch("/api/themes").then((r) => r.json()).then((d) => setThemes(d.themes || [])).catch(() => {});
  }, []);
  const patchBrand = async (body: Record<string, string>) => {
    setBrandBusy(true);
    try {
      const r = await fetch("/api/brand", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({} as any));
      if (r.ok) setBrand(d); else setGenErr(d.detail || t("外观未保存"));
    } catch { setGenErr(t("无法保存外观 — 后端未响应")); } finally { setBrandBusy(false); }
  };
  const uploadLogo = async (f: File) => {
    setBrandBusy(true);
    try {
      const fd = new FormData(); fd.append("file", f);
      const r = await fetch("/api/brand/logo", { method: "POST", body: fd });
      const d = await r.json().catch(() => ({} as any));
      if (r.ok) setBrand(d); else setGenErr(d.detail || t("Logo 上传失败"));
    } catch { setGenErr(t("Logo 上传失败")); } finally { setBrandBusy(false); }
  };
  useEffect(() => { if (defaultVoice && !voice) setVoice(defaultVoice); }, [defaultVoice, voice]);

  const genScript = async () => {
    if (!topic.trim()) {
      setAiErr(t("先给 AI 一个主题 — 它按主题写整段口播稿。")); topicRef.current?.focus(); return;
    }
    setAiBusy(true); setAiErr(null);
    try {
      const r = await fetch("/api/script", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ topic, tone, length: len, lang: "zh" }),
      });
      const d = await r.json();
      if (!r.ok) setAiErr(d.detail || t("生成失败"));
      else setScript(d.script);
    } catch {
      setAiErr(t("无法连接后端"));
    } finally {
      setAiBusy(false);
    }
  };

  // H5: creating a job used to start the whole pipeline, so the outline had nowhere to be
  // reviewed. `hold: true` makes the job exist without running it; 按此大纲生成 starts it.
  const [held, setHeld] = useState<string | null>(null);
  const [outline, setOutline] = useState<{ entries: OutlineRow[]; sections: string[]; est_seconds: number } | null>(null);
  const [olBusy, setOlBusy] = useState(false);

  const fetchOutline = async (jid: string) => {
    const r = await fetch(`/api/jobs/${jid}/outline`, { method: "POST" });
    const d = await r.json().catch(() => ({} as any));
    if (!r.ok) { setGenErr(d.detail || `${t("大纲生成失败")}（HTTP ${r.status}）`); return null; }
    setOutline(d);
    return d;
  };

  const generate = async () => {
    // Every way this can fail must say so on screen — a dead primary button with no
    // reason reads as "nothing happened".
    if (!hasText) {
      setGenErr(t("还没有内容 — 粘贴一段文字，或点上面 ✨ 让 AI 从主题写一段。"));
      taRef.current?.focus();
      return;
    }
    if (!voice) { setGenErr(t("还没选配音音色。")); return; }
    setBusy(true); setGenErr(null);
    try {
      const r = await fetch("/api/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ script, ratio, layout, quality, fps, format, voice, hold: true,
                               llm_plan: llmPlan && llm.ready }),
      });
      const d = await r.json().catch(() => ({} as any));
      if (!r.ok || !d.job_id) {
        setGenErr(d.detail || `创建失败（HTTP ${r.status}）`);
        setBusy(false);
        return;
      }
      setHeld(d.job_id);
      await fetchOutline(d.job_id);
    } catch {
      setGenErr(t("无法连接后端 — 服务还在跑吗？"));
    }
    setBusy(false);
  };

  const backToScript = async () => {
    if (held) await fetch(`/api/jobs/${held}`, { method: "DELETE" }).catch(() => {});
    setHeld(null); setOutline(null);
  };

  const confirmOutline = async (rows: OutlineRow[]) => {
    if (!held) return;
    setOlBusy(true);
    try {
      if (rows.length) {
        const r = await fetch(`/api/jobs/${held}/outline`, {
          method: "PATCH", headers: { "content-type": "application/json" },
          body: JSON.stringify({ entries: rows }),
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({} as any));
          setGenErr(d.detail || t("大纲没能保存")); setOlBusy(false); return;
        }
      }
      await fetch(`/api/jobs/${held}/run`, { method: "POST" });
      onCreate(held);   // stay busy: we are leaving for the Studio, not idle
      return;
    } catch {
      setGenErr(t("无法连接后端 — 服务还在跑吗？"));
    }
    setOlBusy(false);
  };

  if (outline) {
    return <OutlinePanel data={outline} busy={olBusy} onBack={backToScript}
      onRecut={() => held && fetchOutline(held)} onConfirm={confirmOutline} />;
  }

  return (
    <div className="intake">
      <p className="eyebrow">Paste script · one sentence = one beat</p>
      <div className="ai-row llm-row">
        <span className={"llm-chip" + (llm.ready ? " on" : "")} role="status">
          <i className="llm-dot" aria-hidden="true" />
          {llm.ready
            ? <>{t("模型已连通 ·")} <code>{llm.model}</code>{llm.source === "ollama" ? t(" · 本地 Ollama") : ""}{llm.latency_ms !== null ? ` · ${llm.latency_ms}ms` : ""}</>
            : <>{t("模型未连通 · ")}{llm.detail || t("未检测到可用端点")}</>}
          <button className="llm-retry" onClick={() => loadLlm(true)} disabled={llmBusy}
            aria-label={t("重新检测模型连通")}>{llmBusy ? t("检测中…") : t("重试")}</button>
        </span>
      </div>
      <div className="ai-row">
        {llm.ready ? (
          <>
            <input className="fld ai-topic" ref={topicRef} placeholder={t("给 AI 一个主题，自动生成旁白…")} value={topic}
              onChange={(e) => setTopic(e.target.value)} onKeyDown={(e) => e.key === "Enter" && genScript()} />
            <select className="fld ai-sel" value={tone} onChange={(e) => setTone(e.target.value)}>
              <option value="neutral">{t("克制")}</option><option value="warm">{t("温暖")}</option>
              <option value="punchy">{t("有力")}</option><option value="witty">{t("机智")}</option>
            </select>
            <select className="fld ai-sel" value={len} onChange={(e) => setLen(e.target.value)}>
              <option value="short">{t("短")}</option><option value="medium">{t("中")}</option><option value="long">{t("长")}</option>
            </select>
            <button className="ghost" onClick={genScript} disabled={!topic.trim() || aiBusy}>{aiBusy ? t("生成中…") : t("✨ 生成")}</button>
          </>
        ) : (
          <span className="ai-hint">{t("✦ AI 写稿未启用 — 启动")} <code>ollama serve</code> {t("并拉取一个模型后点上面「重试」；或设")} <code>MONOLINE_LLM_BASE_URL</code> / <code>MODEL</code> / <code>API_KEY</code> {t("指向任意 OpenAI 兼容端点。也可直接粘贴文本。")}</span>
        )}
      </div>
      {aiErr && <p className="ai-err">{aiErr}</p>}
      <textarea
        className="script"
        ref={taRef}
        value={script}
        placeholder={t("在漆黑的深海，超过九成的生物都能自己发光。\n这不是反射阳光，而是一场发生在体内的化学反应。")}
        onChange={(e) => setScript(e.target.value)}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && hasText) generate();
        }}
      />
      <div className="opts">
        <div className="opt-group" role="group" aria-label={t("画幅")}>
          <span className="opt-lbl">{t("画幅")}</span>
          <div className="chips">
            {["landscape", "portrait", "square"].map((r) => (
              <button key={r} className={ratio === r ? "chip on" : "chip"} aria-pressed={ratio === r} onClick={() => setRatio(r)}>{r}</button>
            ))}
          </div>
        </div>
        <div className="opt-group" role="group" aria-label={t("分镜判定")}>
          <span className="opt-lbl">{t("分镜")}</span>
          <div className="chips">
            <button className={llmPlan && llm.ready ? "chip on" : "chip"} aria-pressed={llmPlan && llm.ready}
              disabled={!llm.ready} title={llm.ready ? t("规则打底，模型只重判规则判成纯文字的拍") : t("需要模型连通")}
              onClick={() => setLlmPlan(true)}>{t("模型加判")}</button>
            <button className={!llmPlan ? "chip on" : "chip"} aria-pressed={!llmPlan}
              onClick={() => setLlmPlan(false)}>{t("纯规则")}</button>
          </div>
        </div>
        <div className="opt-group" role="group" aria-label={t("版式")}>
          <span className="opt-lbl">{t("版式")}</span>
          <div className="chips">
            {[["minimal", t("极简")], ["editorial", t("杂志")], ["bold", t("醒目")]].map(([v, l]) => (
              <button key={v} className={layout === v ? "chip on" : "chip"} aria-pressed={layout === v} onClick={() => setLayout(v)}>{l}</button>
            ))}
          </div>
        </div>
        <div className="opt-group" role="group" aria-label={t("质量")}>
          <span className="opt-lbl">{t("质量")}</span>
          <div className="chips">
            {[["draft", t("草样")], ["looks", t("标准")], ["delivery", t("高质")]].map(([v, l]) => (
              <button key={v} className={quality === v ? "chip on" : "chip"} aria-pressed={quality === v} onClick={() => setQuality(v)}>{l}</button>
            ))}
          </div>
        </div>
        <div className="opt-group" role="group" aria-label={t("帧率")}>
          <span className="opt-lbl">{t("帧率")}</span>
          <div className="chips">
            {[24, 30, 60].map((f) => (
              <button key={f} className={fps === f ? "chip on" : "chip"} aria-pressed={fps === f} onClick={() => setFps(f)}>{f}</button>
            ))}
          </div>
        </div>
        <div className="opt-group" role="group" aria-label={t("导出格式")}>
          <span className="opt-lbl">{t("格式")}</span>
          <div className="chips">
            {["mp4", "webm", "mov"].map((f) => (
              <button key={f} className={format === f ? "chip on" : "chip"} aria-pressed={format === f} onClick={() => setFormat(f)}>{f}</button>
            ))}
          </div>
        </div>
      </div>
      {voices.length > 0 && (
        <div className="voices" role="group" aria-label={t("旁白音色")}>
          <div className="voices-bar">
            <span className="opt-lbl">{t("音色")}</span>
            <button className="voice-toggle" onClick={() => setVoiceOpen((o) => !o)} aria-expanded={voiceOpen}>
              <span className="voices-cur">{voices.find((v) => v.id === voice)?.label ?? voice}</span>
              <span className="vchev">{voiceOpen ? "▴" : "▾"}</span>
            </button>
            <button className="vplay-btn" onClick={() => audition.toggle(voice)}
              aria-label={audition.playingId === voice ? t("停止试听当前音色") : t("试听当前音色")} title={t("试听")}>
              {audition.loadingId === voice ? <span className="vload" />
                : audition.playingId === voice ? <span className="veq"><i /><i /><i /></span>
                : <span className="vplay" />}
            </button>
          </div>
          {voiceOpen && (
            <div className="voice-groups">
              {groupVoices(voices).map((g) => (
                <div key={g.name} className="voice-cat">
                  <span className="voice-cat-name">{g.name}</span>
                  <div className="voice-chips">
                    {g.items.map((v) => {
                      const on = v.id === voice;
                      const playing = audition.playingId === v.id;
                      const loading = audition.loadingId === v.id;
                      return (
                        <div key={v.id} className={`vchip ${on ? "on" : ""} ${playing ? "playing" : ""}`}>
                          <button className="vchip-pick" onClick={() => setVoice(v.id)} aria-pressed={on} title={`${v.label} · ${v.lang}`}>{v.label}</button>
                          <button className="vchip-play" onClick={() => audition.toggle(v.id)}
                            aria-label={playing ? `停止试听 ${v.label}` : `试听 ${v.label}`}>
                            {loading ? <span className="vload" />
                              : playing ? <span className="veq"><i /><i /><i /></span>
                              : <span className="vplay" />}
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      <div className="brand-box">
        <button className="brand-toggle" aria-expanded={brandOpen} onClick={() => setBrandOpen(!brandOpen)}>
          <span className="bt-lbl">{t("外观 · 品牌")}</span>
          <span className="bt-sum">{themes.find((t) => t.id === brand.theme)?.label || brand.theme} · {brand.label}{brand.logo ? " · Logo ✓" : ""}{brandBusy ? t(" · 保存中…") : ""}</span>
          <span className="bt-caret">{brandOpen ? "▴" : "▾"}</span>
        </button>
        {brandOpen && (
          <div className="appearance brand-body">
            <div className="swatches">
              {themes.map((t) => (
                <button key={t.id} className={`swatch${brand.theme === t.id ? " on" : ""}`} aria-pressed={brand.theme === t.id} title={t.label}
                  style={{ background: t.paper }} onClick={() => patchBrand({ theme: t.id })}>
                  <span className="sw-ink" style={{ background: t.ink }} /><span className="sw-dot" style={{ background: t.accent }} />
                </button>
              ))}
            </div>
            <div className="ap-row">
              <label className="fld-lbl">{t("品牌")}</label>
              <input className="fld" defaultValue={brand.label} onBlur={(e) => e.target.value !== brand.label && patchBrand({ label: e.target.value })} />
            </div>
            <div className="ap-row">
              <label className="fld-lbl">{t("强调色")}</label>
              <input type="color" className="accent-pick" value={/^#[0-9a-fA-F]{6}$/.test(brand.accent) ? brand.accent : "#C4F82A"}
                onChange={(e) => setBrand({ ...brand, accent: e.target.value })} onBlur={(e) => patchBrand({ accent: e.target.value })} />
              {brand.accent && <button className="ghost sm" onClick={() => patchBrand({ accent: "" })}>{t("默认")}</button>}
            </div>
            <div className="ap-row">
              <label className="fld-lbl">Logo</label>
              {brand.logo_url ? <img className="brand-logo-prev" src={brand.logo_url} alt={t("当前 Logo")} /> : <span className="muted">{t("未设置")}</span>}
              <label className="ghost sm file">{brandBusy ? t("载入中…") : t("上传")}
                <input type="file" accept="image/*" hidden disabled={brandBusy}
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadLogo(f); e.target.value = ""; }} />
              </label>
              {brand.logo && (
                <button className="ghost sm" onClick={async () => {
                  const r = await fetch("/api/brand/logo", { method: "DELETE" }); if (r.ok) setBrand(await r.json());
                }}>{t("移除")}</button>
              )}
            </div>
            <p className="bt-note">{t("对之后每个新作业生效；单个作业仍可在出片后到右侧调整。")}</p>
          </div>
        )}
      </div>
      <div className="meta">
        <span>{count ? count.beats : "…"}{t(" 拍")}</span>
        <span>{chars}{t(" 字符")}</span>
        <span>≈ {count ? count.seconds : "…"}{t(" 秒")}</span>
        <span className="spacer" />
        <button className="generate" disabled={busy} aria-busy={busy} onClick={generate}>
          {busy ? t("创建中…") : t("生成 ⌘↵")}
        </button>
      </div>
      {count?.over && (
        <p className="cap-warn" role="alert">
          {t("这段会切成 ")}{count.beats}{t(" 拍，超过一个作业的 ")}{count.cap}{t(" 拍上限。")}
          {t("请按章节拆成几个作业分别生成 — 单条这么长的片会在渲染阶段失败，而不是在这里。")}
        </p>
      )}
      {genErr && <p className="ai-err" role="alert">{genErr}</p>}
    </div>
  );
}

function JobShell({ id, onBack }: { id: string; onBack: () => void }) {
  const { data, refresh } = useHydration(id);
  if (!data) return <div className="status"><span className="dot warn" /> loading…</div>;
  const rerun = async () => { await fetch(`/api/jobs/${id}/run`, { method: "POST" }); refresh(); };
  return <Studio data={data} onBack={onBack} onRun={rerun} refresh={refresh} />;
}

function HistoryView({ onOpen, onNew }: { onOpen: (id: string) => void; onNew: () => void }) {
  const [jobs, setJobs] = useState<any[]>([]);
  useEffect(() => { fetch("/api/jobs?limit=50").then((r) => r.json()).then((d) => setJobs(d.jobs || [])).catch(() => {}); }, []);
  const del = async (id: string) => { await fetch(`/api/jobs/${id}`, { method: "DELETE" }); setJobs(jobs.filter((j) => j.id !== id)); };
  return (
    <div className="intake">
      <div className="hist-head">
        <p className="eyebrow">History · {jobs.length} jobs</p>
        <button className="ghost" onClick={onNew}>+ new</button>
      </div>
      {jobs.length === 0 && <p className="muted">{t("还没有作业。点右上 new 开始。")}</p>}
      <table className="hist">
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id} onClick={() => onOpen(j.id)}>
              <td className="h-thumb">{j.status === "succeeded" && (
                <img loading="lazy" src={`/api/jobs/${j.id}/poster`} alt=""
                  onError={(e) => { e.currentTarget.closest("td")!.classList.add("no-poster"); }} />
              )}</td>
              <td className="h-title">{j.title || "untitled"}</td>
              <td className={`h-status ${j.status}`}>{j.status}</td>
              <td className="h-dur">{j.total_duration ? `${j.total_duration.toFixed(0)}s` : "—"}</td>
              <td className="h-when">{(j.created_at || "").slice(5, 16).replace("T", " ")}</td>
              <td><button className="ghost sm" onClick={(e) => { e.stopPropagation(); del(j.id); }}>{t("删除")}</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Check = { name: string; state: string; found?: string | null; expected?: string | null; fix?: string | null };

const CHECK_LABEL: Record<string, string> = {
  node: "Node 22", ffmpeg: "FFmpeg", gsap_vendored: "GSAP (本地)", ofl_cjk_font: "CJK 字体 (OFL)",
  chrome: "无头 Chrome", hyperframes: "HyperFrames", render_sidecar: "渲染 sidecar",
};
const STATE_TONE: Record<string, string> = { ok: "ok", warn: "warn", will_download: "warn", missing: "bad", error: "bad" };

function SetupView() {
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [ok, setOk] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const load = async () => {
    setBusy(true);
    try {
      const d = await (await fetch("/api/health")).json();
      setChecks(d.checks || []); setOk(!!d.ok);
    } catch {
      setChecks(null); setOk(false);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => { load(); }, []);
  return (
    <div className="intake setup">
      <div className="hist-head">
        <p className="eyebrow">{t("Setup · 环境自检")}</p>
        <button className="ghost" onClick={load} disabled={busy}>{busy ? t("检查中…") : t("重新检查 ↻")}</button>
      </div>
      {checks === null ? (
        <p className="muted">{t("连不上后端。用")} <code>monoline start</code> {t("启动后重试。")}</p>
      ) : (
        <div className="checks">
          {checks.map((c) => (
            <div key={c.name} className={`check ${STATE_TONE[c.state] || "warn"}`}>
              <span className="seg-dot" />
              <div className="check-body">
                <div className="check-top"><span className="check-name">{t(CHECK_LABEL[c.name]) || c.name}</span><span className="check-state">{c.state}</span></div>
                {c.found && <div className="check-found">{c.found}</div>}
                {c.state !== "ok" && c.fix && <div className="check-fix">{t("修复：")}{c.fix}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
      {ok === true && <p className="setup-ok">{t("✓ 环境就绪，可以出片。")}</p>}
    </div>
  );
}

type Route = { view: "new" | "history" | "setup" | "modes" | "job"; jobId?: string };
function parseHash(): Route {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (h.startsWith("job/")) return { view: "job", jobId: h.slice(4) };
  if (h === "history") return { view: "history" };
  if (h === "setup") return { view: "setup" };
  if (h === "modes") return { view: "modes" };
  return { view: "new" };
}

export function App() {
  const [route, setRoute] = useState<Route>(parseHash);
  useEffect(() => {
    const on = () => setRoute(parseHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = (to: string) => { window.location.hash = to; };
  const jobId = route.view === "job" ? route.jobId ?? null : null;
  return (
    <div className={jobId ? "app-root wide" : route.view === "modes" ? "shell wide-page" : "shell"}>
      <header className="head">
        <div className="wm" onClick={() => go("")} role="button"><Logo size={20} /><span className="wm-txt">monoline<span className="dot">.</span></span></div>
        <div className="tag">paste a script. get a film.</div>
        <span className="navspacer" />
        {!jobId && (
          <nav className="nav">
            <button className={route.view === "new" ? "on" : ""} onClick={() => go("")}>New</button>
            <button className={route.view === "history" ? "on" : ""} onClick={() => go("history")}>History</button>
            <button className={route.view === "modes" ? "on" : ""} onClick={() => go("modes")}>Modes</button>
            <button className={route.view === "setup" ? "on" : ""} onClick={() => go("setup")}>Setup</button>
          <button className="lang-toggle" onClick={() => setLang(lang() === "zh" ? "en" : "zh")}
            aria-label={t("切换界面语言")} title={t("切换界面语言")}>
            {LANG_NAME[lang() === "zh" ? "en" : "zh"]}
          </button>
          </nav>
        )}
      </header>
      {jobId ? <JobShell id={jobId} onBack={() => go("history")} />
        : route.view === "history" ? <HistoryView onOpen={(id) => go(`job/${id}`)} onNew={() => go("")} />
        : route.view === "modes" ? <ModesView />
        : route.view === "setup" ? <SetupView />
        : <NewView onCreate={(id) => go(`job/${id}`)} />}
    </div>
  );
}
