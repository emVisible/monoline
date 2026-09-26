# Monoline — 演进路线图（V1–V8，历史记录）

> ⚠️ **这份文件是 2026-09-24 之前的历史快照，别再从这里读现状数字。** 它当时记的是 V1–V30f，
> 之后 V31–V54 的逐条记录在 `docs/VISUAL.md`（带 commit 与实测），现状清单在 `docs/CONFIG.md`
> （有门禁与代码双向比对），下一步计划在 `docs/PLAN.md`。
> 已知过期处（2026-09-26 复核）：写「12 kind」→ 现在 **28**；「18 图标」→ **158**；
> 「内置 12 个音色」→ **25**（中文 8）；「44 测试」→ **105**；「health 7 项」→ **9 项**；
> 「presets 表已建未用」→ 三个端点已接；「仓库非 git」→ 已有 100+ commit。
> 保留原文是为了留当时的判断过程，不作为事实来源。

> 自主迭代计划：以「高级全栈工程师 + 产品经理」双视角，按版本推进 Plan→优化→改正→反馈→构建，直到工具与视觉都趋于完善。每版本是一个可独立交付、可实测的垂直切片。

## 现状基线（已完成）
- 管线：贴文本→切分→逐拍 Kokoro TTS→时长累加对齐→规则分镜（12 kind + 关键词提炼）→Jinja 合成（单色/内嵌 CJK 字体/本地 GSAP）→lint→渲染→MP4。
- 能力：可续跑(P0)、blur crossfade 转场分级(P1)、旁白可编辑重合成(P2)、History+取消(P3)、BGM+闪避(P4)、多画幅+fps/quality/格式导出(P5/M3.4)、Setup/Logo/错误态(P6)、崩溃 reconcile(M3.1)、SSE 实时进度(M3.2)、sidecar 渲染主路+CLI 兜底(M3.3)、竖屏构图填充、字幕随场景溶解。
- 基座：SQLite(presets 表已建未用)、FastAPI/uv、Vite+React+TS+pnpm、`<hyperframes-player>` 实时预览。
- V1 ✅ LLM 写稿 provider 层 + `/api/script`（无 key 优雅降级、prompt 单测）。
- V2 ✅ 视觉主题系统（mono-ink/paper/noir/slate）+ 强调色/品牌 + retheme + presets 存取。
- V3 ✅ 画面素材：V3a 内联 SVG 图标系统（18 图标、按 kind 指派）；V3b 确定性数据可视化（进度环 + 比例条，pct 保守解析）；V3c 图片上传冻结 + image kind + 任意 kind 配图 slot（抽帧验证成片内 file:// 解析）。
- 修复 ✅ 终态 succeeded 只在 deliver 内写 → 缓存重跑/reconcile 会把已完成作业卡死 running；改为 run_pipeline 末尾统一写终态（重启自愈实测通过）。
- 视觉 ✅ 底部极简时间进度条（accent 线性铺满，transform-only GSAP）；数值表格相对条形；小数十进制不再误判为百分比环。

## V1 — LLM 写稿闭环 ✅（产品核心愿景：指派任务→自动生成）
- 后端：provider 无关的 LLM 客户端（OpenAI 兼容 base_url + key，支持本地 Ollama）；`POST /api/script {topic,tone,length,lang}` → 旁白脚本文本（一行一拍）。未配置 key 时优雅降级、明确提示。
- 前端：NewView 顶部「主题 → AI 生成脚本」，结果灌入 textarea 可继续手改；生成中动效。
- 成功判据：给定主题产出可拍脚本并一键进入既有渲染管线；无 key 时不报错、给出配置指引；prompt 单测过。

## V2 — 视觉主题系统 + 品牌定制 ✅
- 多主题（mono-ink / mono-paper + 新增 2–3 套配色/字重/圆角），主题选择器（NewView + Studio）；品牌名/强调色/字体可配；用 presets 表存「配方」（主题+画幅+质量+字体）一键套用。
- 成功判据：切主题成片配色/字风随动、预览即时刷新；保存/载入预设闭环。

## V3 — 画面素材能力（图标 / 图片 / 数据可视化）✅
- 场景支持 image / icon / 图表 slot；媒体解析与本地冻结（对齐 media-use 理念）；stat/compare/list 版式接入图标与配图，摆脱纯文字。
- 成功判据：带图/带图标场景渲染正确、字体子集与素材相对路径无越界、lint 过。

## V4 — Studio 交互与动效打磨（基本完成）
- ✅ V4a 节拍拖拽重排：HTML5 拖拽 + 音频跟随（零重 TTS）+ plan 同步重排 + recompose；`POST /reorder`（非排列 422）。
- ✅ V4b 键盘选拍导航：←/→ 或 j/k 逐拍、Home/End、1–9 跳拍、输入框内不劫持、选中滚动跟随、快捷键提示（浏览器结构实测通过）。
- ✅ V4a′ 切换 kind 自动补齐可编辑槽位（cards/table/list/compare 现可手动切换并编辑）。
- ✅ V4c 节拍选中联动预览 seek：点选/键盘导航即 seek 到该拍（偏移越过入场转场）。
- V4d（可选）时间轴拖动条、微交互与过渡再统一、空/加载/错误态再打磨。
- 成功判据：重排→plan 顺序更新→预览随动；快捷键覆盖常用操作；交互无卡顿。

## V5 — 交付增强（进行中）
- ✅ V5a 字幕导出 SRT/VTT：`GET /api/jobs/{id}/subtitles?fmt=`，纯函数由段级时间戳生成（跳过空拍、重编号）；Studio 加下载链接；修 CJK 文件名 header（RFC5987）。
- ✅ V5b 封面/首帧缩略图：`GET /api/jobs/{id}/poster` 懒抽标题帧（避开黑场）+ 缓存 + 回填旧作业；Studio「封面」下载链接。
- V5c 批量作业（并发受控）— 单用户本地工具，优先级低，暂缓。
- 成功判据：一次作业产出 mp4 + srt + 封面 ✅。

## V6 — 逐词字幕 + 音频精修（可选云 TTS）
- 接入返回逐词时间戳的云 TTS（HeyGen/ElevenLabs，key 可配）→ karaoke 逐词高亮；音频母带精修（响度归一、旁白 EQ）。本地无 key 时保持句级。
- 成功判据：云 TTS 时逐词字幕同步、本地时不回归。

## V7 — 稳健性 / 质量 / 文档（进行中）
- ✅ V7a 冷启动自检 `make warmup`（内置 fixture 端到端出片 + 自清理）；Makefile 版本漂移修复（用本地 hyperframes 二进制）；README Status/tokens/tooling 校正；+4 API 路由护栏测试（17 passed）。
- ✅ V7b 无障碍：全局 :focus-visible 焦点环、reduced-motion 覆盖动画、Shift+←/→ 键盘重排、Studio live-region 播报状态/进度/错误 + 面板 aria-label（浏览器实测通过）。
- V7c 前端逻辑护栏（可选 Vitest）、错误恢复与日志再打磨、渲染性能采样。
- 成功判据：关键路径有测试护栏 ✅；冷启动到出片一条命令 ✅；文档准确 ✅。

## V8 — 自定义音色（试听 + 创建后改音色）✅
- 后端：`voices.py` 内置 12 个 Kokoro 音色注册表（id/label/lang/group，phonemizer lang 由音色前缀派生，二者锁死）；`GET /api/voices` + `GET /api/voices/{id}/sample`（首次合成、缓存到 `cache/voices/{id}.wav`，未知音色 422）；create 校验音色并同步 `config.lang`；`POST /api/jobs/{id}/voice` + `revoice()`（逐拍重 TTS→重拼接→重定时→recompose，文本不变故不重规划，bump 版本让预览重载）。
- 前端：NewView 按语言分组的音色选择 + ▶ 试听（首合成 loading 点、播放中均衡器动效，选中态 accent 填充）；Studio「配音」面板音色下拉（optgroup 分组）+ 试听 + 改音色「重合成中…」busy + 失败回滚。
- 验证：后端 29 测试（+6 音色护栏，退出码单取）；试听 zh/en/ja 实测出 wav 且缓存命中 1.6ms；端到端 af_heart→am_adam 旁白音频 md5 改变（1afc6168→4cb7841d）、逐拍时长随之变、成片重渲染 succeeded；NewView/Studio 无头 Chrome 截图确认版式与选中态。
- 成功判据：选内置音色 → 试听 → 创建后改音色 → 重合成出片，全链路实测通过 ✅。
- 已知边界（非本期）：仅内置音色、无逐拍混排；把中文脚本切到外语音色会连带改 phonemizer 语言（Kokoro 设计使然），未来可加「将切换旁白语言」提示。

## V9 — 视觉：从「文字流」到「PPT 级动效」（进行中，逐切片）
> 目标边界：只做「PPT 类动效视频」做到媲美 Gamma/Beautiful.ai/Keynote 那种精致度，不做剪辑/真人替代。
> 对标提炼（不闭门造车）：Gamma/Beautiful.ai（版式层级+留白+克制动效）、Prezi/Keynote（空间叙事与 magic-move 连续感）、
> kinetic-typography 说明片流派（分层入场、逐词/逐行揭示、强调节奏）、HeyGen/HyperFrames 动效生态（rules/blueprints/transitions）。
> 现状基线：每场 `.sbody` 作为**整块**淡入+上浮 → 观感像「文字流」。下面按杠杆从高到低排切片，每片实现→渲染→抽帧/截图核验→提交。
- ✅ V9-1 背景纵深：`#bg` 升级为「accent 径向柔光 + 次级 ink 光 + 基础渐变」分层，营造景深与品牌感，accent 仍克制。抽帧核验。
- ✅ V9-2 分层入场：每场 icon→eyebrow→headline→sub→行/项 依次错峰 reveal（transform+opacity、stagger 0.09），替代整块出现。零模板改动（选择器 `.scene-icon/.scene-media/.inner > *`）。
- ✅ V9-3 动能标题：展示型大字 `.headline/.s-title/.term/.q` 用 clip-path inset 从左到右擦入 + 落定，与次要元素分层。
- ✅ V9-4 版式破居中 + 强调规：主画面文案加 accent 强调规 scaleX 绘入；statement/section 采编辑式左对齐栏，与 title/summary 居中形成错落。
- V9-5 强调动效：stat 数字滚动、可视化环/条描画、关键词随旁白高亮弹入。
- ✅ V9-6 章节页：section 拍按序编号（planner 填 index 01/02…）+ 超大 accent 序号 + 编辑式左对齐 + → 图标 + accent 规 + 标题擦入，成 PPT 章节分隔页；横竖屏抽帧核验无溢出。（mask-wipe/push 额外转场类型仍待做。）
- ✅ V9-5 数据可视化描入：stat 环 stroke-dashoffset 从空描入、表格条 scaleX 生长（transform/stroke-only）。
- ✅ V9-6 章节页：section 按序编号（planner 填 index 01/02…）+ 超大 accent 序号 + 编辑式版式 + → 图标 + accent 规；横竖屏抽帧核验。
- ✅ V9-7 环境光漂移：#glow 柔焦 accent 光晕随全片缓慢漂移（sine.inOut），注入呼吸感氛围动效，不遮文字。
- ✅ V9-8 转场分级新增方向推入：进入 stat/list/table/cards/compare 用横向 push（xPercent ±16 + fade），叙事类仍 blur，section 竖向 slide、summary 慢 blur 不变。（mask-wipe 仍可选。）
- ✅ V10 语义图标：planner 对无默认图标的 kind（statement/note 等）按旁白文本关键词自动挑图标（`icons.pick_icon`，中英子串映射，命中即止、无则留空），画面摆脱纯文字。单测覆盖映射与白名单。
- ✅ V11 版式风格 presets（整片三档）：`render_composition(layout=)` + `<body data-layout>` + CSS 变体，端到端贯通（CreateJob/ConfigPatch 存 config、runner/recompose 读取、NewView 版式 chips、Studio 版式控制）。三档：minimal（居中，原样）· editorial（左对齐杂志栏、光晕右移）· bold（accent 实心药丸 eyebrow + 更大标题，经 `--hl-scale` 乘算自适应字号）。未知 layout 失败关闭到 minimal。抽帧核验三档肉眼可辨、横屏+竖屏均无溢出、`make warmup` 绿、后端 31 测试全过。
- ✅ V13 字幕版式化：caption 随 data-layout 分化——editorial 左下 lower-third + accent 左描边 + 左对齐；bold 居中加粗 + 厚 accent 左条 + 更强底色；minimal 原样。三档同帧抽帧核验各异。
- ✅ V14 数据类方向化入场：stat/list/table/cards/compare 内层内容从左滑入（x:-30→0 + stagger），与横向 push 转场构成视差（场景自右推入、内容自左错峰），叙事类仍上浮；稳态不变、transform-only 确定性。grep 生成的时间线 JS + 抽帧错峰核验。
- ✅ V15 stat 数字滚动 count-up：`engine.count_up` 解析干净数值核+前后缀（千分位/多数字/纯文字→None 静态回退），stat.html.j2 渲染 `.cu` span（data-to/dec/start），时间线末尾一段 querySelectorAll('.cu') 代理 tween 做 0→目标滚动，与环描同步。抽帧核验 1.89s=50%、3.99s=92%（seek 下确定、后缀 % 保留）。count_up 契约单测 + 后端 32 测试全过；warmup 绿。（注：改 engine.py 需重启服务，模板才热重载。）
- ✅ V16 表格/卡片逐行错峰：table/cards 的行嵌在 `.rows` 里、此前整块入场。现把 `.rows` 从块入场选择器排除，对 `.row` 单独加左滑 stagger（0.11）；list/compare 的行本是 `.inner` 直接子元素、V14 已逐行。抽帧核验 1.85s 三行由上到下渐显、3.6s 齐平；护栏单测锁「table/cards 各 1 条 row tween、叙事场景无」；后端 33 测试全过、warmup 绿。
- ✅ V17 UI 无障碍：NewView 五组切换 chips（画幅/版式/质量/帧率/格式）+ 音色选择 + Studio 版式/主题，选中态此前仅靠 CSS `.on` 颜色、辅助技术读不出。现全部补 `aria-pressed`，opt-group 加 `role="group"`+`aria-label`。浏览器 evaluate 核验 DOM：版式组 role/label 到位、极简 pressed=true 其余 false。
- ✅ V18 列表标记剥离（贴文本观感修复）：实测发现粘贴 `- 要点` / `1. 步骤` 时，标记会漏进标题/字幕/TTS（画面出现「- 快速启动」这种原始文本），且 `2. x` 被误判成 stat。段分器在按行切拍前用 `_LIST_MARK`（要求标记后带空白）剥离 `- * + • · 1. 2) 3、` 等；`3.14`/`-10%` 因无尾随空格不受影响。护栏单测覆盖剥离+小数/负数安全；后端 34 测试全过、warmup 绿。
- ✅ V19 英文句子切分（英文内容不再糊成一整拍）：`_SENT_SPLIT` 此前只认 `。！？`，英文段落里的 `.` 不是句末边界 → 一段英文变成一条 90 字 wall-of-text（正是段分器要消灭的 M1 故障，而目标明确要英文）。现加 `(?<=\.)(?=\s)`：句末点号后跟空白才切，`3.14`/`$5.5` 不切；`_TRAIL` 加 `.` 去掉标题尾点；`_merge_tiny` 合并片段按 ASCII 边界补空格（`U.S.`+`API.`→`U.S. API.`，CJK 不加）。实测英文三段正确切分、小数安全；后端 35 测试全过、warmup 绿。（注：warmup 与运行中的服务争用 SQLite 写锁，需停服后跑。）
- ✅ V20 markdown 标题标记剥离：`_LIST_MARK` 扩到 `#{1,6}\s+`，粘贴 `# 标题` 不再把 `#` 漏进画面；`C#`（行中）与 `#hashtag`（无空格）不受影响。实测 + 单测覆盖；后端 35 测试全过、warmup 绿。
- ✅ V21 列表项不被误合并（修 V18 回归）：剥离标记后短条目（如「设计系统」4 字）跌破 `min_chars`，会被 `_merge_tiny` 折进相邻拍变成「设计系统构建模型上线服务」这种流水账。段分器现记录「带标记的行=刻意条目」并保护其不参与合并；普通短碎片仍照常合并。广域输入扫描（12 例）触发发现；单测锁行为；后端 36 测试全过、warmup 绿。
- ✅ V22 粘贴含 URL 不再整单崩溃：`assert_determinism` 的 `https?://` 判据过宽，把旁白/标题正文里的链接（自动转义、无害）也判为违规 → compose 直接抛错、出不了片。收窄为仅拦远程资源（`src/href/poster=…http`、`url(http`、`@import`），文本里的 URL 放行。7 例断言核验（文本 URL 过、远程 img/script/@import/url() 仍拦、本地相对过）；后端 37 测试全过、warmup 绿。
- ✅ V23 markdown 行内语法清理：粘贴自文档/LLM 的 `**粗**`/`[文字](链接)`/`` `代码` ``/`*斜*` 会把标记漏进画面与 TTS。段分器按行去标记只留可见文字（`2 * 3` 这种夹空格的星号不误判为斜体、裸 URL 保留交给 V22 渲染）。实测 + 单测；后端 38 测试全过、warmup 绿。
- ✅ V24 前端拍数估算与后端切分对齐：NewView 的「N beats」此前只数换行，单行多句（"深海会发光。这不是…。"）显示 1 但实际渲染 3 拍，误导。改为按句末标点（CJK 。！？ + 拉丁 `.` 后跟空白，`3.14` 安全）估算，与段分器一致；副标题改「one sentence = one beat」。浏览器实测：3 句输入现显示 3 beats；tsc/build 干净。
- ✅ V25 品牌 Logo（功能克展）：`Brand.logo` 新字段（默认空、向后兼容），`POST/DELETE /jobs/{id}/logo` 冻结图片到 composition/assets 并 retheme→recompose，`#brand` 锁定处渲染 `<img class="brand-logo">`（40px、与文字并排），Studio 外观面板加上传/移除。实测：上传 favicon 作 logo → 标题页左上角正确显示、与站点图标统一；后端 39 测试全过、warmup 绿、tsc/build 干净。
- ✅ V26 时长估算校准：NewView 的「≈Ns」按 6s/拍估算，实测中文约 3s/拍（25 字句 ≈4s），翻倍误差误导选段。改为 3s/拍；浏览器实测 3 句输入显示 ≈9s。
- ✅ V27 基础图元层：画面从「文字组合」进入「可渲染成图的剪接模式」（用户直接要求拓展基础组件）：
  - 原子 `.node`（胶囊按钮：可选序号/图标 + 标签，surface 底 + 描边 + 投影）是三种新 kind 共用的唯一图元。
  - `flow` 流程图：箭头链（`→ ⇒ ➜ -> =>`）拆成节点，中间用 SVG 箭头连接，超宽自动折行。
  - `radial` 导图：中心 hub（accent 实心）+ 双侧分支，连线是 compose 期算好的归一化 viewBox 坐标（绝不在 tween 期读 DOM）；竖屏改为顶部 hub 向下扇形展开，避免 9:16 溢出。
  - `steps` 步骤时间线：序号胶囊 + 左侧轨道，轨道 `scaleY` 自上而下填充。
  - 动效：kind 专属编排——标题落下 → 胶囊 `back.out` 逐个弹出（stagger 0.16）→ 连线/分支随后显影；三 kind 不再走通用整块淡入，也不画图标（图本身就是图）。转场并入「数据类」push。
  - 判定范围同步扩大：planner 新增 `rules:arrow-chain` / `rules:hub-enumeration`（「X 分为/包括/涵盖 A、B、C」）/ `rules:ordinal-chain`（①②③ / 第 N 步）三条抽取规则；段分器把「引导句：箭头链」拆成两拍（引导句是句子、链是图，1 拍 1 镜时不拆就丢图），k:v 行与 、枚举仍保持整拍。
  - 版式 preset 与画幅联动：editorial 左对齐、bold 加粗描边/加粗标题；竖屏图元字号 38px、导图高度 900px。
  - 实测：贴一段含链/分层/序号的中文段落 → 自动出 flow + radial + steps 三镜并成功出片（作业 succeeded，18.2s），抽帧确认三种图均正确成图、无溢出；后端 44 测试全过（+5）、warmup 绿、tsc/build 干净。
- ✅ V30 生成流程与旁白表现力（用户四点：点了没反应/生成中不该出现 card/外观该放生成前/旁白匀速且标点被念出来）：
  - **零静默失败**：主按钮不再 disabled 到无处申诉——空内容点击给出「还没有内容 — 粘贴一段文字，或点 ✨ 让 AI 写一段」并聚焦输入框；POST 期间显示「创建中…」；后端 422（如 60 拍上限）直接显示。AI 写稿空主题同样给原因。**并查出真凶之一：index.html 无 Cache-Control，浏览器拿旧 bundle → 行为永远是旧代码**，`SpaStatic` 对 html 加 `no-store`（哈希 asset 仍可缓存）。
  - **阶段解耦**：RUNNING 时右侧属性面板只留「先生成，再调整」的进度提示，配置/逐拍编辑卡 0 个（浏览器实测）；终态才出现。
  - **外观前移**：主题/品牌/强调色/Logo 变成用户级身份 `brand.json`（GET/PATCH /api/brand、POST/DELETE /api/brand/logo），首页「外观 · 品牌」区设定后对每个新作业生效；create_job 兜底并把 Logo 冻结进作业 assets（实测新作业带 `Acme 实验室` + `#FF7A5A` + logo img）。修掉 `Path("") == cwd` 让首次上传去 `unlink('.')` 的 500。
  - **标点不再被念出来**（取证→修）：`%` 实测被读成 "percent"、`**` 读成 "asterisk asterisk"（非中文段走英文 G2P）。新增 `narration.clean()`：破折/箭头→逗号停顿、省略号→长停顿、emoji/markdown 符号/裸 % 删除；`92%` 仍读「百分之九十二」。两条 TTS 路（misaki 与 espeak 回退）共用。
  - **停顿与语气**：`is_phonemes=True` 下逗号不是 stop，Kokoro 的 sentence/clause_pause 对整句几乎无效（实测 5.35s 里只有两处 0.15s）。改为按分句切块分别合成、由我们插入真实呼吸（从句 0.20s、句末 0.42s、省略/破折 0.62s，并裁掉每块自带尾静音避免叠加），语速按行形状选（数字/短句 0.90、常规 0.97、长句 1.04）。成片旁白实测：分句呼吸 0.26-0.28s、破折号处 0.66s。诚实边界：Kokoro 没有音高参数，「语气起伏」能控的是节奏与停顿，真要语调变化得换模型或云 TTS。
  - 后端 51 测试全过（+4：品牌往返/标点不拼读/分句/SPA no-store）、tsc/build 干净、warmup 绿。
- ✅ V30f 纵向拓展基础模块（用户：还要更多组件提高表现力）：新增三种成图 kind，全部复用 `.node`/条形图元 + compose 期算好的几何，场景总数 16→19。
  - `arch` 分层堆叠：宽度自下而上递减（地基最宽），顶层带 accent 描边与 L1/L2/L3 序号；动效是**自底向上**搭建（`stagger {from:"end"}`）。判定：`_LAYER_MARK`（三层/分层/底层…）+ 枚举 → 「X 分为 A、B、C 三层」不再被误当成分支导图。
  - `cycle` 环形闭环：`viz.polar()` 在 compose 期算出环上锚点，节点坐同一坐标，弧段 + accent 端点 + 中央幽灵数字；判定：箭头链首尾回环（含「更多内容」这种带定语的回归）或「循环/闭环/飞轮/雪球」等词。
  - `funnel` 漏斗：`funnel_widths()` 归一化到最大值并强制单调不增、下限 26% 保证末段可读；动效条形自中心横向展开。判定：≥3 组「词+数字」或 k:v 数值阶梯。
  - 漏斗只在**数值非递增**时成立：「2019 100 万、2020 300 万、2021 900 万」这种增长序列会被 flat-line 成等宽漏斗 = 画假图，改判回普通形态（真要画它需要 timeline 组件，已列入候选）。
  - 顺带修掉 V27 遗留瑕疵：节点名里的量词尾巴（「监控**四层**」「存储**三层**」）现在会被剥掉。
  - 三种新 kind 都进 DIAGRAM_KINDS（不出字幕、不画图标、走 push 转场），Studio 可选并自动补齐槽位。抽帧确认三种图正确成形；后端 54 测试全过（+3）。
- 附 UI：NewView 音色选择器折叠化，主流程回到一屏（收起态 + aria-expanded + 展开 25 音色，浏览器点按核验）。
- ✅ V29 接上本地 Ollama（用户起了 `batiai/gemma4-e4b:q4`，要求「联通 + 界面提示是否连通」）：
  - **目标解析**：`llm/client.py::detect()` — 显式 `MONOLINE_LLM_*` 优先，否则探活本地 Ollama（`/api/tags`）并选模型；结果缓存 15s，探活延迟回给前端。`/api/script/status` 从「读配置」改成「真探活」（旧实现只判 env，永远显示未配置=假提示）。
  - **界面提示**：NewView 顶部状态胶囊 `● 模型已连通 · batiai/gemma4-e4b:q4 · 本地 Ollama · 50ms` / `○ 模型未连通 · <真实错误>` + 「重试」（`?refresh=1`）；未连通时「模型加判」自动禁用并回落「纯规则」。Setup/`/api/health` 新增 `llm` 与 `zh_tones` 两项（软检查，不阻塞出片）。
  - **分镜判断接入形态（按实测证据定的）**：规则打底 + 模型只重判规则判成 `statement` 的弱拍。原因：让 7.5B 全量出分镜实测 83s、6 拍只回 5 项（破坏 1拍=1镜）、`stat` 槽位形状不守，还把箭头链/「分为四层」判成 `list`（规则现在出的是真图）。逐拍校验：kind 必须注册、槽位形状必须对、每个字必须来自该拍（防编造）、结尾不能是「是/的/了…」这类截断词；不合格就保留规则结果，拍数永远不变。
  - 实测：同一份 6 拍稿 `asked 4 / upgraded 3 / rejected 1`，三句纯文字变成 `stat 三个小时`、`stat 两分钟`、`definition 确定性渲染`，抽帧确认画面正确；断网态（指向关闭端口）胶囊显示真实错误、按钮禁用、提示给出 `ollama serve` 指引。踩到两个坑：`response_format: json_object` 下要求「裸数组」会让 Ollama 只回一个对象就停（改成 `{"scenes":[…]}`）；Python 不热重载，改完提示词必须重启才生效。
  - `make warmup` 显式 `llm_plan:false`：自检只证自己的工具链，不依赖可选模型服务（带上会从 18.6s 涨到 50.7s）。后端 47 测试全过（+4）、tsc/build 干净。
- ✅ V28 中文声调修复（用户报「所有中文都是一个方言味，我要普通话」）——根因不是音色：kokoro-onnx 用 espeak-ng 做中文 G2P，espeak 把声调写成数字（1/2/3/4/5），而 Kokoro 词表只有 114 个符号、**不含任何数字**，`Tokenizer.phonemize` 又会把词表外字符**静默丢掉**。实测：`妈/马/骂` 过滤后音素完全相同、`师/诗/史/市` 全塌成一个 `s.ˈi.`，且丢失发生在 speaker embedding 之前 → 换任何音色都没救。
  - 修法：新增 `monoline/tts_zh.py`，中文改走 misaki 的 `ZHG2P`（声调映射成模型训练时真正见过的箭头 → ↗ ↓ ↘，全部在词表内），再用 kokoro-onnx 的 `is_phonemes=True` 直送；拉丁词交回 espeak `en-us`（misaki 会原样透传、而大部分 ASCII 字母不在词表）。顺带：cn2an 把「3倍/92%」读成中文、流程图旁白里的 `→` 变成停顿而不是被念出来。
  - 路由点选在 `HF.tts()`（4 个调用点一次覆盖：TTS 阶段/改音色/改旁白重合成/试听）；模型未下载或 misaki 缺失时**自动回退**旧 CLI 路径，绝不因缺依赖整单失败。试听 wav 缓存文件名加 `.r2` 版本位，防止旧的无声调样本继续被端出去。
  - 证据：`妈麻马骂` → `ma→ ma↗ ma↓ ma↘`（4 个不同、0 丢字），`师/诗` 仍同音（正确）、`ʂ` 声母回来了；真实作业服务端 wav 与本地声调路径**逐比特相同**（max|diff|=0.000000），试听端点同样一致；`/api/health` 新增 `zh_tones` 检查项（ok/will_download/warn）。后端 45 测试全过（+2）、warmup 绿。
  - 依赖：`misaki[zh]`（纯 Python：pypinyin/jieba/cn2an 等）进 `tts` extra + uv.lock；已征得同意后才装。
  - 连带修掉的第二个缺陷（否则声调进不了成片）：compose/gate/render/deliver 的缓存键用的是 `st`（只有旁白**文本**），改音色时 `st` 不变 → 重跑时 render 被判「已缓存」跳过，新配音只进了 index.html、mp4 仍是旧声。改为用 `av`（文本+音色+lang+语速）。实测：同一作业改音色后 `POST /run`，mp4 从 18.196s 变 16.083s（= 新旁白时长）、mtime 刷新。
- 成功判据：抽帧对比明显「非文字流」✅；`make warmup` 绿 ✅；后端测试不回归（29）✅；每切片有渲染证据 ✅。

## 执行原则
- 每版本先写最小可测后端，再接前端，端到端抽帧/实测验证后才算完成；只做加法不破坏既有绿测。
- 证据优先：退出码单独取、截断≠不存在、界面「已保存」要改→存→重读。
- 不静默装系统依赖；push/打 tag 需单独同意（本地 commit 可自便）。

## 当前状态（as-of 2026-09-24，自主迭代收口点）
- ✅ 已完成：V1（LLM 写稿）· V2（主题/品牌/presets）· V3（图标/数据可视化/图片）· V4（拖拽重排/键盘/预览 seek/kind 槽位补齐）· V5（SRT/VTT/封面/History 画廊）· V7a（warmup 冷启动自检/文档/护栏测试）· V7b（focus-visible/reduced-motion/aria-live/键盘重排）· V8（自定义音色：注册表/试听/创建后改音色重合成）。
- ✅ 端到端审计中修复的真实缺陷（8 个）：终态卡 running、分号拆碎 k:v 行、distill 弱标题（连接词/引导从句/时间从句）、list 模板 slots.items 崩溃、note 双图标、note/quote 字幕重复、预览写死 16:9、小数十进制误判环、emoji 整单失败、Setup 健康检查误报。
- ✅ 全 16 个场景 kind 均经渲染帧确认（V27 起含 flow/radial/steps 三种成图组件）；四域内容（科普/营销/技术/叙事）分类与标题合理；`make warmup` 绿；后端 44 测试全过；`/api/health` 7 项全绿。
- ⏳ 未完成 / 下一步：
  1. V6 逐词字幕 —— 依赖返回词级时间戳的云 TTS（HeyGen/ElevenLabs，需 key），本地 Kokoro 只给整句时长，故句级字幕是当前的诚实上限；接云 TTS 后加 karaoke 高亮。
  2. V7c 前端逻辑单测（Vitest）—— 需新增 dev 依赖，按约定应先征得同意。
  3. 可选视觉：视频内进度条已加；进一步可做分 kind 的入场动效差异（V27 已给三种图元单独编排，其余 kind 仍可细分）。
  4. 图元层继续扩：`matrix`（四象限）、`arch`（分层堆叠图）、`cycle`（环形闭环）、`funnel`（漏斗）——都复用 `.node` 原子，只差布局算子与判定规则。
  5. 解锁多拍成图：`1 拍 = 1 镜` 不变式让粘贴的 markdown 表格/编号列表被拆成碎拍。放开为「一镜可跨 N 拍」（旁白/字幕仍按拍，画面按镜）后，才能把 6 行表格、4 条列表渲染成一张完整图表。这是图元层的下一个容量瓶颈。
  6. 判定精度：规则规划器已覆盖链/分层/序号；再接 `LLMPlanner`（协议槽已留，走同一 validator，需 `MONOLINE_LLM_API_KEY`）把「无标记但语义成图」的内容也判出来，规则兜底离线可用。
- 交接：仓库非 git（未擅自 `git init`）；`make start` 起服务（:8787，sidecar :8790）；`make warmup` 自检；数据在 `~/Library/Application Support/Monoline/`。
