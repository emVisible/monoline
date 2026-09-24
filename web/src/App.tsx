import { useEffect, useRef, useState } from "react";
import { Studio } from "./Studio";
import { Logo } from "./Logo";
import { groupVoices, useAudition, useVoices } from "./voices";

type Stage = { key: string; seq: number; status: string; duration_ms?: number | null; error?: string | null };
type Artifact = { id: string; kind: string; rel_path: string; mime: string; size_bytes: number; state: string };
type Job = { id: string; slug: string; title: string; status: string; total_duration: number | null; error: string | null };
type Ev = { id: number; stage: string | null; kind: string; level: string; message: string | null };
type Hydration = { job: Job; stages: Stage[]; segments: any[]; artifacts: Artifact[]; plan: any | null; events: Ev[] };

const STAGE_ORDER = ["script", "tts", "assemble", "plan", "fonts", "compose", "gate", "render", "deliver"];

const STAGE_LABEL: Record<string, string> = {
  script: "切分", tts: "语音合成", assemble: "拼接旁白", plan: "分镜规划",
  fonts: "字体子集", compose: "生成画面", gate: "质检", render: "渲染", deliver: "出片",
};

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
  const [aiReady, setAiReady] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiErr, setAiErr] = useState<string | null>(null);
  const { voices, default: defaultVoice } = useVoices();
  const [voice, setVoice] = useState("");
  const [voiceOpen, setVoiceOpen] = useState(false);
  const audition = useAudition();
  const lines = script.split("\n").map((l) => l.trim()).filter(Boolean);
  const chars = script.replace(/\s/g, "").length;

  useEffect(() => {
    fetch("/api/script/status").then((r) => r.json()).then((d) => setAiReady(!!d.ready)).catch(() => setAiReady(false));
  }, []);
  useEffect(() => { if (defaultVoice && !voice) setVoice(defaultVoice); }, [defaultVoice, voice]);

  const genScript = async () => {
    if (!topic.trim()) return;
    setAiBusy(true); setAiErr(null);
    try {
      const r = await fetch("/api/script", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ topic, tone, length: len, lang: "zh" }),
      });
      const d = await r.json();
      if (!r.ok) setAiErr(d.detail || "生成失败");
      else setScript(d.script);
    } catch {
      setAiErr("无法连接后端");
    } finally {
      setAiBusy(false);
    }
  };

  const generate = async () => {
    setBusy(true);
    try {
      const r = await fetch("/api/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ script, ratio, layout, quality, fps, format, voice }),
      });
      const d = await r.json();
      if (d.job_id) onCreate(d.job_id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="intake">
      <p className="eyebrow">Paste script · one line = one beat</p>
      <div className="ai-row">
        {aiReady ? (
          <>
            <input className="fld ai-topic" placeholder="给 AI 一个主题，自动生成旁白…" value={topic}
              onChange={(e) => setTopic(e.target.value)} onKeyDown={(e) => e.key === "Enter" && genScript()} />
            <select className="fld ai-sel" value={tone} onChange={(e) => setTone(e.target.value)}>
              <option value="neutral">克制</option><option value="warm">温暖</option>
              <option value="punchy">有力</option><option value="witty">机智</option>
            </select>
            <select className="fld ai-sel" value={len} onChange={(e) => setLen(e.target.value)}>
              <option value="short">短</option><option value="medium">中</option><option value="long">长</option>
            </select>
            <button className="ghost" onClick={genScript} disabled={!topic.trim() || aiBusy}>{aiBusy ? "生成中…" : "✨ 生成"}</button>
          </>
        ) : (
          <span className="ai-hint">✦ AI 写稿未启用 — 设置 <code>MONOLINE_LLM_API_KEY</code>（或指向本地 Ollama）后可从主题自动生成，或直接粘贴文本。</span>
        )}
      </div>
      {aiErr && <p className="ai-err">{aiErr}</p>}
      <textarea
        className="script"
        value={script}
        placeholder={"在漆黑的深海，超过九成的生物都能自己发光。\n这不是反射阳光，而是一场发生在体内的化学反应。"}
        onChange={(e) => setScript(e.target.value)}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && lines.length) generate();
        }}
      />
      <div className="opts">
        <div className="opt-group">
          <span className="opt-lbl">画幅</span>
          <div className="chips">
            {["landscape", "portrait", "square"].map((r) => (
              <button key={r} className={ratio === r ? "chip on" : "chip"} onClick={() => setRatio(r)}>{r}</button>
            ))}
          </div>
        </div>
        <div className="opt-group">
          <span className="opt-lbl">版式</span>
          <div className="chips">
            {[["minimal", "极简"], ["editorial", "杂志"], ["bold", "醒目"]].map(([v, l]) => (
              <button key={v} className={layout === v ? "chip on" : "chip"} onClick={() => setLayout(v)}>{l}</button>
            ))}
          </div>
        </div>
        <div className="opt-group">
          <span className="opt-lbl">质量</span>
          <div className="chips">
            {[["draft", "草样"], ["looks", "标准"], ["delivery", "高质"]].map(([v, l]) => (
              <button key={v} className={quality === v ? "chip on" : "chip"} onClick={() => setQuality(v)}>{l}</button>
            ))}
          </div>
        </div>
        <div className="opt-group">
          <span className="opt-lbl">帧率</span>
          <div className="chips">
            {[24, 30, 60].map((f) => (
              <button key={f} className={fps === f ? "chip on" : "chip"} onClick={() => setFps(f)}>{f}</button>
            ))}
          </div>
        </div>
        <div className="opt-group">
          <span className="opt-lbl">格式</span>
          <div className="chips">
            {["mp4", "webm", "mov"].map((f) => (
              <button key={f} className={format === f ? "chip on" : "chip"} onClick={() => setFormat(f)}>{f}</button>
            ))}
          </div>
        </div>
      </div>
      {voices.length > 0 && (
        <div className="voices" role="group" aria-label="旁白音色">
          <div className="voices-bar">
            <span className="opt-lbl">音色</span>
            <button className="voice-toggle" onClick={() => setVoiceOpen((o) => !o)} aria-expanded={voiceOpen}>
              <span className="voices-cur">{voices.find((v) => v.id === voice)?.label ?? voice}</span>
              <span className="vchev">{voiceOpen ? "▴" : "▾"}</span>
            </button>
            <button className="vplay-btn" onClick={() => audition.toggle(voice)}
              aria-label={audition.playingId === voice ? "停止试听当前音色" : "试听当前音色"} title="试听">
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
                          <button className="vchip-pick" onClick={() => setVoice(v.id)} title={`${v.label} · ${v.lang}`}>{v.label}</button>
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
      <div className="meta">
        <span>{lines.length} beats</span>
        <span>{chars} chars</span>
        <span>≈ {Math.round(lines.length * 6)}s</span>
        <span className="spacer" />
        <button className="generate" disabled={!lines.length || busy || !voice} onClick={generate}>
          {busy ? "…" : "Generate ⌘↵"}
        </button>
      </div>
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
      {jobs.length === 0 && <p className="muted">还没有作业。点右上 new 开始。</p>}
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
              <td><button className="ghost sm" onClick={(e) => { e.stopPropagation(); del(j.id); }}>删除</button></td>
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
        <p className="eyebrow">Setup · 环境自检</p>
        <button className="ghost" onClick={load} disabled={busy}>{busy ? "检查中…" : "重新检查 ↻"}</button>
      </div>
      {checks === null ? (
        <p className="muted">连不上后端。用 <code>monoline start</code> 启动后重试。</p>
      ) : (
        <div className="checks">
          {checks.map((c) => (
            <div key={c.name} className={`check ${STATE_TONE[c.state] || "warn"}`}>
              <span className="seg-dot" />
              <div className="check-body">
                <div className="check-top"><span className="check-name">{CHECK_LABEL[c.name] || c.name}</span><span className="check-state">{c.state}</span></div>
                {c.found && <div className="check-found">{c.found}</div>}
                {c.state !== "ok" && c.fix && <div className="check-fix">修复：{c.fix}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
      {ok === true && <p className="setup-ok">✓ 环境就绪，可以出片。</p>}
    </div>
  );
}

type Route = { view: "new" | "history" | "setup" | "job"; jobId?: string };
function parseHash(): Route {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (h.startsWith("job/")) return { view: "job", jobId: h.slice(4) };
  if (h === "history") return { view: "history" };
  if (h === "setup") return { view: "setup" };
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
    <div className={jobId ? "app-root wide" : "shell"}>
      <header className="head">
        <div className="wm" onClick={() => go("")} role="button"><Logo size={20} /><span className="wm-txt">monoline<span className="dot">.</span></span></div>
        <div className="tag">paste a script. get a film.</div>
        <span className="navspacer" />
        {!jobId && (
          <nav className="nav">
            <button className={route.view === "new" ? "on" : ""} onClick={() => go("")}>New</button>
            <button className={route.view === "history" ? "on" : ""} onClick={() => go("history")}>History</button>
            <button className={route.view === "setup" ? "on" : ""} onClick={() => go("setup")}>Setup</button>
          </nav>
        )}
      </header>
      {jobId ? <JobShell id={jobId} onBack={() => go("history")} />
        : route.view === "history" ? <HistoryView onOpen={(id) => go(`job/${id}`)} onNew={() => go("")} />
        : route.view === "setup" ? <SetupView />
        : <NewView onCreate={(id) => go(`job/${id}`)} />}
    </div>
  );
}
