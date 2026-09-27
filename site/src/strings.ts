// Copy for the marketing page. Two rules the page has to hold itself to:
//   1. every number here is measured from the product, not remembered (see site/README.md
//      for the commands that re-derive them);
//   2. no adjective that a screenshot cannot prove. "Powerful", "seamless", "revolutionary"
//      are banned by review, not by convention.
export type Pair = { en: string; zh: string };

export const STRINGS = {
  nav_source: { en: "Source", zh: "源码" },
  a11y_skip: { en: "Skip to content", zh: "跳到正文" },
  rail_aria: { en: "pipeline stages", zh: "管线阶段" },
  frame_caption: { en: "Studio · beats / preview / inspector", zh: "工作台 · 节拍 / 预览 / 单拍检查器" },
  frame_alt: {
    en: "Monoline Studio: the beat list, a live preview and the per-beat inspector, all in English",
    zh: "Monoline 工作台：节拍列表、实时预览与单拍检查器，界面为中文",
  },

  hero_kicker: { en: "Local · monochrome · deterministic", zh: "本地运行 · 单色 · 确定性" },
  hero_line1: { en: "One sentence.", zh: "一句话，" },
  hero_line2: { en: "One beat.", zh: "一拍，" },
  hero_line3: { en: "One slide.", zh: "一屏。" },
  hero_sub: {
    en: "Monoline turns a text script into a narrated explainer video on your own machine.",
    zh: "把一段文字变成一条带旁白的说明视频，全程在你自己的机器上完成。",
  },
  demo_caption: {
    en: "Real output of the segmenter: 8 sentences in, 8 beats out.",
    zh: "切分器的真实输出：8 句进，8 拍出。",
  },
  demo_source_label: { en: "Input", zh: "输入" },
  demo_beats_label: { en: "Beats", zh: "节拍" },

  b2_title: { en: "Nine stages. Each one cached.", zh: "九个阶段，逐级缓存。" },
  b2_sub: {
    en: "Stop it anywhere. The next run resumes where it stopped, and a re-run never overwrites a storyboard you shaped by hand.",
    zh: "任何一步都能停。下次运行从断点继续；重跑不会覆盖你手动调整过的分镜。",
  },
  b2_note: { en: "A forced run repaints. It does not re-author.", zh: "强制重跑只重画，不重写。" },

  b3_title: { en: "28 ways to show a sentence.", zh: "28 种呈现一句话的方式。" },
  b3_sub: {
    en: "A number becomes a figure. A comparison becomes two columns. A sequence becomes a rail. The layout is chosen from what the line says, not from a template you pick.",
    zh: "数字会变成图形，对比会变成两栏，顺序会变成时间轴。版式由这句话说了什么决定，而不是由你选的模板决定。",
  },
  b3_note: { en: "Every kind is reachable from the outline, including the two no rule can ever guess.", zh: "每一种都能从大纲触发，包括规则永远猜不到的那两种。" },

  b4_title: { en: "Review the outline before the audio is paid for.", zh: "在付出音频成本之前，先审阅大纲。" },
  b4_sub: {
    en: "Merge, split, delete, reorder, re-type a beat, attach pictures to it. This runs before synthesis, so restructuring costs seconds instead of a re-render.",
    zh: "合并、拆分、删除、重排、改写、挂图，都发生在合成之前——结构调整只消耗秒级时间，不必重渲。",
  },

  b5_title: { en: "Same input, same film.", zh: "相同输入，相同成片。" },
  b5_sub: {
    en: "Timing is measured voice duration tiled on a timeline, not an ASR guess. There is no randomness, no clock read during render, and no network call in the core path.",
    zh: "时间轴由逐句实测时长铺成，不靠语音识别猜测。渲染过程无随机、无读表时钟、核心链路不联网。",
  },
  b5_stat_tests: { en: "tests green", zh: "测试全绿" },
  b5_stat_voices: { en: "voices, 8 Chinese", zh: "个音色，中文 8 个" },
  b5_stat_icons: { en: "inline icons", zh: "个内联图标" },
  b5_stat_themes: { en: "themes × 3 layout presets", zh: "套主题 × 3 种版式预设" },

  b6_title: { en: "Runs where you run it.", zh: "就在你的机器上跑。" },
  b6_sub: {
    en: "One Python process owns the job store, the pipeline, the workspace and the interface. A stateless render sidecar is spawned by it and dies with it.",
    zh: "一个 Python 进程持有作业库、管线、工作区与界面；渲染 sidecar 由它拉起、随它退出。",
  },
  b6_req1: { en: "Python 3.11 via uv", zh: "Python 3.11（uv 管理）" },
  b6_req2: { en: "Node 22", zh: "Node 22" },
  b6_req3: { en: "FFmpeg on PATH", zh: "FFmpeg 在 PATH 中" },
  b6_req4: { en: "About 2 GB of disk", zh: "约 2 GB 磁盘" },
  b6_note: { en: "No account. No upload. No telemetry.", zh: "无账号、不上传、无遥测。" },

  b7_title: { en: "Get it.", zh: "开始。" },
  b7_step1: { en: "Install", zh: "安装" },
  b7_step2: { en: "Run", zh: "运行" },
  b7_cta: { en: "Open the repository", zh: "打开仓库" },
  b7_note: {
    en: "MIT licensed. The vendored animation runtime keeps its own terms; both are listed in LICENSE.",
    zh: "源码以 MIT 授权。内置的动画运行时保留其自身条款，两者都在 LICENSE 中列明。",
  },

  footer: { en: "Monoline · a local text-to-video pipeline", zh: "Monoline · 本地文字转视频管线" },
} satisfies Record<string, Pair>;

export type StringKey = keyof typeof STRINGS;

/** The nine pipeline stages, in order. Mirrors STAGES in the backend on purpose: the
 *  marketing page names them, so a rename there has to be visible here. */
export const STAGES: Pair[] = [
  { en: "Segment", zh: "切分" },
  { en: "Voice", zh: "语音合成" },
  { en: "Assemble", zh: "拼接旁白" },
  { en: "Storyboard", zh: "分镜规划" },
  { en: "Fonts", zh: "字体子集" },
  { en: "Compose", zh: "生成画面" },
  { en: "Check", zh: "质检" },
  { en: "Render", zh: "渲染" },
  { en: "Deliver", zh: "出片" },
];

/** The 28 scene kinds, straight out of the IR registry (`monoline.ir.sceneplan.KINDS`),
 *  grouped by family so the grid reads as four ideas instead of 28 words. */
export const KINDS: string[] = [
  // text
  "title", "statement", "section", "definition", "quote", "note", "summary", "split", "poster",
  // data
  "stat", "trend", "bars", "kpi", "share", "table", "list", "cards", "compare", "matrix",
  // structure
  "flow", "radial", "steps", "arch", "cycle", "funnel", "timeline",
  // pictures — the two no rule can ever reach; the outline triggers them
  "image", "showcase",
];
