# Monoline — 演进路线图（V1–V8）

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
- V9-6 章节感 & 转场：section 整幅章节页（accent 铺满+超大序号+规线扫过）；补 mask-wipe/push 分级转场。
- V9-5 强调动效：accent 下划线绘制、stat 数字滚动、可视化环/条描画、关键词随旁白高亮弹入。
- V9-6 章节感 & 转场升级：section 做整幅章节页（accent 铺满+序号+规线扫过）；补 mask-wipe/push 等分级转场。
- 成功判据：抽帧对比明显「非文字流」；`make warmup` 绿；后端测试不回归；每切片有渲染证据。

## 执行原则
- 每版本先写最小可测后端，再接前端，端到端抽帧/实测验证后才算完成；只做加法不破坏既有绿测。
- 证据优先：退出码单独取、截断≠不存在、界面「已保存」要改→存→重读。
- 不静默装系统依赖；push/打 tag 需单独同意（本地 commit 可自便）。

## 当前状态（as-of 2026-09-24，自主迭代收口点）
- ✅ 已完成：V1（LLM 写稿）· V2（主题/品牌/presets）· V3（图标/数据可视化/图片）· V4（拖拽重排/键盘/预览 seek/kind 槽位补齐）· V5（SRT/VTT/封面/History 画廊）· V7a（warmup 冷启动自检/文档/护栏测试）· V7b（focus-visible/reduced-motion/aria-live/键盘重排）· V8（自定义音色：注册表/试听/创建后改音色重合成）。
- ✅ 端到端审计中修复的真实缺陷（8 个）：终态卡 running、分号拆碎 k:v 行、distill 弱标题（连接词/引导从句/时间从句）、list 模板 slots.items 崩溃、note 双图标、note/quote 字幕重复、预览写死 16:9、小数十进制误判环、emoji 整单失败、Setup 健康检查误报。
- ✅ 全 13 个场景 kind 均经渲染帧确认；四域内容（科普/营销/技术/叙事）分类与标题合理；`make warmup` 绿；后端 29 测试全过；`/api/health` 7 项全绿。
- ⏳ 未完成 / 下一步：
  1. V6 逐词字幕 —— 依赖返回词级时间戳的云 TTS（HeyGen/ElevenLabs，需 key），本地 Kokoro 只给整句时长，故句级字幕是当前的诚实上限；接云 TTS 后加 karaoke 高亮。
  2. V7c 前端逻辑单测（Vitest）—— 需新增 dev 依赖，按约定应先征得同意。
  3. 可选视觉：视频内进度条已加；进一步可做分 kind 的入场动效差异（需能看动效的核验手段）。
- 交接：仓库非 git（未擅自 `git init`）；`make start` 起服务（:8787，sidecar :8790）；`make warmup` 自检；数据在 `~/Library/Application Support/Monoline/`。
