# 配置与接口清单（唯一事实源）

这份文件是「跑起来需要什么、能调什么」的**唯一**清单。`test_docs_surface_matches_the_app_v53`
会拿它和运行时的真实注册表逐条比对：写在这里的命令/端点不存在 → 红；代码里有而这里没写 →
也红。所以它不会像旧 ROADMAP 那样悄悄过期。

数字快照：2026-09-26，`make test` 105 passed。

## 1. `make` 目标

| 目标 | 作用 |
|---|---|
| `make help` | 列出全部目标 |
| `make bootstrap` | 三件套依赖一次装齐（backend uv / web pnpm / sidecar pnpm） |
| `make backend` `make web` `make sidecar` | 分别只装其中一件 |
| `make start` | **日常就这一个**：后端 + sidecar + 浏览器打开 `:8787` |
| `make serve` | 只起后端（不起 sidecar、不开浏览器） |
| `make dev` | 后端 + Vite 热更新前端 |
| `make test` | **门禁就这条**：backend pytest + `cd web && pnpm exec tsc --noEmit` |
| `make doctor` | 环境自检（node 22 / ffmpeg / gsap / 字体 / chrome / hyperframes / sidecar…） |
| `make warmup` | 冷启动自检：真跑一条极短作业，确认端到端可用 |
| `make fonts` | 重新生成 OFL 字体子集 |
| `make clean` | 清构建产物 |

改前端后**别忘了** `cd web && pnpm build`：SPA 产物落在 `backend/src/monoline/static/` 并由后端同源服务，
而它不在 `make test` 里（只跑 tsc 类型检查）。

## 2. 环境变量（`backend/src/monoline/settings.py`）

| 变量 | 默认 | 用途 |
|---|---|---|
| `MONOLINE_APP_DIR` | `~/Library/Application Support/Monoline` | 作业库 `app.db` 与 `workspaces/<jobid>/` 的根 |
| `MONOLINE_HOST` | `127.0.0.1` | 绑定地址 |
| `MONOLINE_PORT` | `8787` | 唯一对用户暴露的端口（SPA + API + `/w/` 同源） |
| `MONOLINE_SIDECAR_PORT` | `8790` | Node 渲染 sidecar（由 Python 起停，不对外） |
| `MONOLINE_STATIC_DIR` | 包内 `monoline/static` | SPA 构建产物位置 |
| `MONOLINE_HF_VERSION` | `0.8.63` | HyperFrames 全家桶锁版本（producer/player/CLI 必须同版） |
| `MONOLINE_RENDER_VIA_SIDECAR` | `1` | 设 `0` 强制走 CLI 子进程渲染（sidecar 兜底路径的开关） |
| `MONOLINE_LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容端点；本地 Ollama 填 `http://127.0.0.1:11434/v1` |
| `MONOLINE_LLM_API_KEY` | 空 | localhost 端点免 key（见 `llm_ready`） |
| `MONOLINE_LLM_MODEL` | `gpt-4o-mini` | 写稿与分镜升格用的模型名 |
| `MONOLINE_LLM_BATCH_BEATS` | `3` | 分镜升格每批拍数上限（小本地模型不被整篇压垮）。实测 7.5B q4 解码约 1 字/秒，一拍真答案 ≈70 秒，12 拍的批永远跑不完 |
| `MONOLINE_LLM_BATCH_CHARS` | `900` | 每批字符上限，与上一条共同决定分批 |
| `MONOLINE_LLM_PLAN_SECONDS` | `150` | 整轮分镜升格的墙钟预算；用尽后剩下的批**不问**，那些拍按规则保留并在日志里记为 `skipped_batches` |
| `MONOLINE_NODE_BIN` | 空=自动解析 | 显式指定 node 22 可执行文件 |
| `MONOLINE_PYTHON` | 当前解释器 | TTS/字体子集用的 Python（必须 3.11，kokoro-onnx 无 3.14 wheel） |

## 3. CLI（`backend/src/monoline/cli.py`）

`monoline serve` · `start` · `doctor` · `run-script <script.txt>` · `warmup` · `fonts`

`run-script` 是**不打开浏览器**也能出片的通路（文档 `noscript` 兜底里写的就是它，门禁比对过命令名）。

`serve` 与 `start` 都受**单实例门禁**约束（`backend/src/monoline/instance.py`）：启动时读
`$MONOLINE_APP_DIR/instance.json`，只有当里面记录的进程**既存活、其端口又能连通**时才拒绝
（退出码 2）。两个条件缺一不可——只判进程存活会被 PID 复用误伤，只判端口会被「端口被别人
占着」误伤；而崩溃留下的陈旧锁两个条件都不满足，照常启动并续跑（M3.1 的能力不能丢）。
需要并行实例时给其中一个换 `MONOLINE_APP_DIR`。这条门禁来自一次真实事故：第二台实例接管了
第一台正在渲染的 377 秒作业，把同一部片子渲了两遍。

## 4. HTTP 接口（32 条路径，2026-09-26 实测；`/api/*` 是 SPA 的全部依赖）

作业与运行：
- `POST /api/jobs` 建作业（`script` 必填；**超过 1200 拍在入口就 422**，见 V47b；`hold: true` 只建不跑，给上面的大纲步骤用）
- `GET /api/jobs` 列表（返回对象 `{"jobs": [...]}`，不是数组） · `GET /api/jobs/{jid}` 水合（job+stages+segments+artifacts+plan+events）
- `POST /api/jobs/{jid}/run`（`?force=1` 强制重跑各阶段：**重画，但不重写人写过的东西** —— 大纲/Studio 存下的手动分镜（`source="manual"`）在 force 下同样被沿用，只有机器分镜（`llm`）会被重新推导；不带 force 的重跑与续跑两者都不动）
- `POST /api/jobs/{jid}/outline` 只做「切分 + 分镜」，不碰音频，返回整片大纲（每拍：文本 / kind / 所属章节 / 预计秒数）· `GET /api/jobs/{jid}/outline` 读当前大纲 · `PATCH /api/jobs/{jid}/outline` 把用户改过的大纲（合并 / 拆分 / 删除 / 改文本 / 钉住文字类 kind）落成 segments + `source=manual` 的 plan，之后的运行按它走
- `POST /api/jobs/{jid}/cancel` · `DELETE /api/jobs/{jid}`（连工作区一起清）
- 作业状态：`draft`（建了没跑）→ `queued`（**已请求运行、在等那唯一的一个 worker**）→ `running` → `succeeded` / `failed` / `cancelled`。渲染是串行的（concurrency=1），一部六分钟的片子能把后面的作业压住十几分钟 —— 所以「排队中」必须是一个状态而不是沉默（V71）
- `GET /api/jobs/{jid}/stream` SSE 实时进度（前端唯一的进度来源） · `GET /api/jobs/{jid}/events` 轮询尾巴，给 CLI 与调试

逐拍编辑（都走 recompose，秒级刷新预览、不重渲）：
- `PATCH /api/jobs/{jid}/plan/scenes/{i}` 改 kind/slots · `PATCH /api/jobs/{jid}/segments/{i}` 改旁白文本（重合成该拍语音）
- `POST /api/jobs/{jid}/plan/scenes/{i}/suggest` 问模型**这一拍**换个什么形状（只返回建议，不落盘；实测本机模型 0.3–0.85 字/秒，整片批量问不可行，故按拍请求）
- `POST /api/jobs/{jid}/reorder` 拖拽重排 · `POST /api/jobs/{jid}/voice` 换音色 · `PATCH /api/jobs/{jid}/config` 换主题/强调色/品牌

素材与交付：
- `POST /api/jobs/{jid}/assets` 配图 · `POST|DELETE /api/jobs/{jid}/logo` · `POST|DELETE /api/jobs/{jid}/bgm`
- `GET /api/jobs/{jid}/download` · `GET /api/jobs/{jid}/subtitles?fmt=srt|vtt` · `GET /api/jobs/{jid}/poster`
- `GET /w/{job_id}/{rel}` 合成产物（含路径包含性检查）

元信息与写稿：
- `GET /api/health`（9 项自检） · `GET /api/themes` · `GET /api/icons` · `GET /api/voices` · `GET /api/voices/{vid}/sample`
- `GET|PATCH /api/brand` 用户级默认外观 · `POST|DELETE|GET /api/brand/logo`
- `GET|POST /api/presets` · `DELETE /api/presets/{pid}`
- `POST /api/script`（主题→口播稿） · `GET /api/script/status`（探活） · `POST /api/script/preview`（**拍数只由它出**，见 V47b）

## 5. 已知的「建了但没用」

不删它们各自有理由，但别误以为它们生效：

- `SIDECAR_TOKEN`（`supervisor.py`）：生成并注入，但 sidecar **从不校验**。留着是将来接鉴权的钩子。
- 从不写入的列：`job_stages.duration_ms`（已从 API 撤下）、`job_stages.attempts`、
  `artifacts.remote_token` / `remote_expires_at`。DROP 要写迁移，单用户本地库不值得。
- `scene_plans.warnings_json`：**写入但无人读**——没有端点返回它，前端零消费。所以「把可疑拍提示给
  用户并让他一键删」这条设计必须先补 API + UI，不是加一条判据就完事。

## 6. 不许动的不变量

- **1 拍 ↔ 1 段音频 ↔ 1 场景**（IR 契约）。V54b 要动的就是它，动之前先读 `docs/PLAN.md` 的 V54 段。
- 渲染产物只有一个 `<audio id="vo">`（多轨混音在本地渲染里走不通，见 `pipeline/audio_mix.py`）。
- 成片必须确定性：无 `Math.random` / `Date.now`，几何在 compose 期算完，只动 transform/opacity。
- DB 里的 plan 是编辑后的唯一真相源，`ir/scene_plan.json` 只是 rules 初值、可能 stale。
