# Monoline

![Monoline：一句、一拍、一屏](web/public/og.png)

**贴入文稿，产出成片。**

Monoline 是一个纯本地、单用户使用的文稿转视频工具：输入一段文字，输出一条带旁白的说明视频。
视觉为单色极简，全流程在本机完成——无需账号、无需上传、核心链路不依赖网络。

它不是剪辑器，也不是生成式视频模型，而是一条确定性管线：文稿被切分为节拍，每个节拍按内容
判定类型并套用对应版式，每拍独立合成语音并以其真实时长占用时间轴，最终由 HTML 渲染为 MP4。
相同输入始终得到相同成片。

[English documentation](README.md)

## 作业流程

```
输入文稿 → 大纲（审阅与调整） → 九个阶段 → MP4 → Studio（继续精修）
```

1. **贴入文本，或由模型生成。** 来自文档、README 或模型回复的 Markdown 按「块」而非「源码行」
   解析，标题符、列表符、表格分隔与脚注标记既不会上屏，也不会进入旁白。
2. **在付出音频成本之前先审阅大纲。** 节拍切分结果与逐拍分镜同时呈现，可合并、拆分、删除、
   重排、改写，或为某拍挂载图片。此阶段位于 TTS 之前，结构调整只消耗秒级时间。
3. **九个阶段，逐级缓存。** `script → tts → assemble → plan → fonts → compose → gate → render →
   deliver`。进程中断后重启即从断点续跑。重跑不会覆盖人工调整过的分镜：`?force=1` 只重画，
   不重写。
4. **出片后在 Studio 继续精修。** 逐拍重新配音、改写画面文案、更换场景类型与版式处理、拖拽
   重排（音频跟随）、键盘导航、实时预览。

时间轴由测量值推导，不做估算：逐句合成、逐句取时长、依次铺满。链路中不含 ASR 环节——Whisper
对中文合成语音的解码并不可靠，确定性路径同时也是更准确的路径。

## 环境要求

| | |
|---|---|
| **uv** | Python 版本锁定 3.11（`kokoro-onnx` 未发布 3.14 wheel） |
| **Node 22** | 见 `.nvmrc`；按绝对路径解析，其他主版本会明确报 `wrong_version` |
| **ffmpeg + ffprobe** | 需在 `PATH` 中（`brew install ffmpeg`） |
| **磁盘** | 约 2 GB：Chrome Headless Shell、Kokoro 模型、渲染帧缓存 |

可选的模型能力（写稿、逐拍分镜建议）对接 OpenAI 兼容端点或本机 Ollama；未配置时自动回落到
规则路径，不影响出片。

## 快速开始

```bash
make bootstrap   # uv sync（py3.11）+ pnpm install + producer 解析 + hyperframes doctor
make start       # 按需构建 → 拉起渲染 sidecar → 打开 http://127.0.0.1:8787
```

`make doctor` 输出解析后的真实环境状态，`make help` 列出全部目标。

开发模式（热更新）：一个终端 `make serve`，另一个终端 `pnpm --filter @monoline/web dev`，
访问 `http://127.0.0.1:5173`。

修改前端后需执行 `pnpm --filter @monoline/web build`；构建产物由后端从
`backend/src/monoline/static/` 同源提供。`make test` 只做类型检查，不包含构建。

**一个数据目录对应一个服务进程。** `monoline start` 会续跑数据库中处于运行态的作业——这在
进程崩溃后是正确的，在另一个服务进程仍持有这些作业时则是破坏性的。因此启动时会检测：若锁
记录中的进程存活且其端口可连通，则拒绝启动。确需并行实例时，请为其指定独立的
`MONOLINE_APP_DIR`。

## 架构

单个 Python 进程即产品本体：持有作业库（SQLite）、管线、按作业隔离的工作区，并同源提供
Web 界面。渲染由 Python 拉起并随之退出的 Node sidecar（HyperFrames producer server）承担，
该进程无状态。

```
backend/   Python（uv）：FastAPI + 管线 + SQLite + sidecar 监管   → uv run monoline …
web/       Vite + React + TypeScript（pnpm）：单色界面与实时预览
site/      Vite + React + TS + Motion：对外宣传页，单独部署到 Vercel
sidecar/   Node：@hyperframes/producer startServer，无状态渲染末端
design/    界面与画面共用的设计令牌（4 套主题 + ui.json）
docs/      CONFIG.md（对外接口现状）· VISUAL.md（逐版台账）· PLAN.md · ROADMAP.md（历史快照）
```

`site/` 直接读取 `design/tokens/ui.json` 而不是复制一份，宣传页的配色因此不可能与产品走偏；
部署步骤见 [`site/README.md`](site/README.md)（该文件为英文）。

渲染链路为 HTML→MP4，依赖 [HyperFrames](https://github.com/heygen-com/hyperframes)
（Apache 2.0）；动画运行时为 [GSAP](https://gsap.com)，随仓库本地内置以保证离线与确定性。

### 核心不变量

**一拍 ↔ 一段旁白 ↔ 一个场景。** 所有阶段都依赖该约束，因此它在端到端流程中被断言，而非
默认成立。它也是「把这两页合并」属于设计问题而非开关问题的原因。

## 命令目标

| 目标 | 作用 |
|---|---|
| `make test` | 门禁：后端 pytest 加 `tsc --noEmit`。请以此为准，不要临时单跑 pytest |
| `make warmup` | 内置样例端到端渲染，冷启动验收 |
| `make doctor` | 解析后的环境真实状态（node / ffmpeg / chrome / 字体 / sidecar） |
| `make bootstrap` | 安装全部依赖并校验渲染工具链 |
| `make start` | 构建 → 拉起 sidecar → 打开应用 |

## 文档

[`docs/README.md`](docs/README.md) 说明各文档的权威性与保鲜期。

- **`docs/CONFIG.md`** — 工具对外能力全表：make 目标、环境变量、CLI 命令、全部 HTTP 端点，
  以及刻意未接线的部分。有测试将其与运行中的应用双向比对，因此不会静默失效。
- **`docs/VISUAL.md`** — 视觉要素清单与逐版台账，每行都附有做出该变更时所依据的实测数字。
- **`docs/PLAN.md`** — 当前计划，以及已被实测否掉的方向清单。
- **`docs/ROADMAP.md`** — V1–V30 阶段叙事，其中数字为当时的冻结快照。

## 现状

纯本地、单用户、无鉴权。以下数字于 2026-09-26 实测，`make test` 为 **140 项通过**：

**28** 种场景类型 · **158** 个内联 SVG 图标 · **25** 个音色（中文 8 个）· **4** 套单色主题 ×
**3** 种版式预设 · **3** 种画幅 · 导出 MP4 / WebM / MOV · SRT / VTT 字幕 · 封面抽取 · 界面
中英双语 · **32** 个 HTTP 路径。

- **编辑** — TTS 之前的大纲审阅、三栏 Studio、逐拍重新配音、拖拽重排、可浏览的呈现模式库
  （`#/modes`）、逐拍向模型请求更换形状。
- **画面** — 整片版式轮换，相邻节拍不重复同一形状；确定性数据可视化（进度环、条形、环形占比、
  迷你趋势线、KPI、四象限矩阵）；结构图（流程、放射、步骤、层级、循环、漏斗）；图片素材与
  统一的单色影调处理；按叙事位置分级的模糊交叉淡化与方向性转场；跟随旁白节奏的逐条揭示；
  公式经内置 KaTeX 渲染。
- **声音** — 本地 Kokoro 合成；背景音乐以侧链压缩为旁白让路；标点符号不发音。
- **中文排版** — 上屏标点由单一模块负责（GB/T 15834 与 clreq），按场景类型分别约束，中英文
  之间自动留白，仅清理首尾冗余标点以保留句中有效标点。

## 许可

MIT，见 [LICENSE](LICENSE)。

MIT 授权范围是 Monoline 自身源码。内置与运行时下载的第三方组件保留各自条款，已在同一文件中
逐项列出：GSAP（GreenSock Standard License）、KaTeX（MIT）、Lucide（ISC）、Noto Sans SC
（SIL OFL 1.1）、HyperFrames（Apache 2.0）、Kokoro-82M 模型权重（Apache 2.0）。
