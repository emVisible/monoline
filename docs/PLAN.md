# Monoline 深度优化计划（V47–V53）

制定日期 2026-09-25。三层证据：① 真实作业语料 **43 作业 / 311 拍**（已剔除合成测试稿，
关键词 `取消测试 / 用来撑拍数 / 第N句 / 测试第`）；② 本地代码逐文件审计（file:line 见各条）；
③ 同类产品横向调研（Gamma / Beautiful.ai / Synthesia / 剪映图文成片 / PowerPoint Morph /
Keynote Magic Move / GSAP SplitText / GB/T 15834 / W3C clreq）。

每条版本的「实测问题」都是可复算的数字，不是感觉；验收口径都写成能一条命令判定的形式。

---

## 0. 一句话诊断

画面已经不像「生成的」，但**分镜选择是逐拍、无上下文、无配额**的，而**呈现文本的标点是
11 处各自为政的 Python 正则**——所以问题集中在两处：讲法太少（44.4% 的拍都是同一种
statement），以及上屏文字带着旁白的标点。前者是 V49，后者是 V48。

---

## V47 输入侧：长文本不再报错，模型按块喂（健壮性 / 可延展性）

**实测问题**
- `HEAD` 里 `segment.py:59/118` 是 `max_beats=60` 直接 `raise`：真实语料里已有 1 例
  （job 001a0d6f7f7…，70 拍）整单失败，且是在作业**已入库入队之后**才失败（`routes_jobs.py:19`
  只有 `min_length=1`，没有上限校验），界面表现为「跑了一下然后红了」。
- LLM 侧原先**一次请求带全部弱拍**：本地 7.5B q4 的实测后果记录在 `llm/planner.py:3-9`
  （83s、6 拍只回 5 条、槽位被改形）。用户说的「容易把内存崩掉」就是这条路径。
- `client.py:118-144` 构造请求体**没有 `max_tokens` / `num_ctx` / `stop`**：输出长度完全
  由服务端决定，截断的 JSON 死在 `parse_json`，而 Ollama 上下文溢出的表现是「少回几条」，
  `merge()` 会静默把那些拍留在 statement——即**没有任何一处知道它失败了**。

**已交付（本轮）**
- `hard_cap=240` 取代 60 拍硬错，报错文本带上字符数与折算时长（≈分钟）；
- `llm/planner.py` `_batches()`：按 **拍数 + 字符** 双预算顺序分批，单批失败只损失该批
  （`stats["failed_batches"]`，并在 `runner.py:214-218` 打进作业日志，不再静默）；
- 预算进 `Settings`：`MONOLINE_LLM_BATCH_BEATS=12` / `MONOLINE_LLM_BATCH_CHARS=900`，
  按模型改，不改代码。

**待办（V47b）**
- 分批目前是**无上下文**的：每批只看那 12 拍，章节编号与叙事弧线在批界处断裂。
  改为结构优先（`\n\n` → `\n` → `。` → `；` 递归，512 字窗口 + 10–20% 重叠），
  并把上一批尾部拍 + 滚动大纲带进下一批 prompt。
- 摄入端 `App.tsx:372` 的「N beats」计数是**前端自己另写的一套正则**（`/[\n。！？!?…]+/`），
  看不见 `_CLAUSE_SPLIT`/`_split_structured`/`_merge_tiny`，所以计数器与后端真实拍数在
  40 字长句和冒号箭头行上已经不一致——要么由后端出数，要么删掉前端估算。
- 给 `/api/jobs` 加 `max_length` 的前置校验：错误必须在**创建前**返回，不是跑一半再红。

**验收**：90 拍脚本能出片；`llm_batch_beats=3` 时批数与批大小随设置变化（已有测试）；
V47b 后，跨批的 section 序号连续、章节标题不重复。

---

## V48 中文上屏文本的标点契约（正确性 / 文本质量）

**实测问题（311 拍）**
- **43 处（13.8%）显示文本以标点收尾**，其中 **17 处（5.5%）以「，、：」结尾**——半句被
  当成大标题（根因是 `_split_long` 把长句劈开，见 #113）。
- **4 处引号不配对**：跨拍被切开后各留一半，例如 `探寻在经济领域可以取得哪些成果”`、
  `将让双方“有更多时间,`（还混进一个半角逗号）。
- 用户说的「重复标点」，机制查清了是**双重包引号**：`_QUOTE_WRAP`（`planner.py:22`）把整拍
  引号剥掉存进 `q`，`kinds/quote.html.j2:2` 又无条件加回 `“…”`，于是作者写的「」变成
  `“增长靠的是复利。”`——外层引号是模板造的，句号还在引号里面。
- 规则散在 **11 处 Python**（`planner.py:54/57/426`、`_strip_number`、list/steps/radial/timeline
  各自的 strip、`segment.py:98`、`narration.py:47-57`），**模板与 CSS 里一条都没有**。
  而且 `_TRAIL`（`planner.py:54`）不含 `，、`，`_LEAD_PUNCT` 却含——所以尾逗号天然漏网。
- `narration.py` 里现成的 `，，→，`、`，。→。` 去重规则**只服务音频**（只被 `hf/cli.py:113`
  和 `tts_zh.py:114` 调用），显示路径一条都没用上。

**要交付**
1. 单一 `display_text.py` 规则层（纯函数 + 表驱动），按 kind 出规则：
   - **hero 类**（statement / title / summary / section / definition 的 term）：按
     **GB/T 15834-2011 附录 B.4**「标题末尾不用终止标点，问号叹号省略号除外」去 `。 ，、；：`；
   - **引用类**（quote / poster / note）：保留句内标点，但**补全配对**（半引号要么补全要么剥掉），
     并且模板不再无条件加外层引号（改由 slot 决定）；
   - 全类：折叠连续标点、全/半角归一、CJK↔拉丁/数字之间插 ¼ em 空格（clreq）。
2. 11 处旧 strip 全部收敛到这一层；模板只渲染，不再自己处理标点。
3. 修根因而非症状：`_split_long` 劈出的半句不得升格为 hero（与 #113 合并处理）。
4. 显示与旁白共用同一套去重，避免「画面没标点、旁白念出标点」之外的第三种状态。

**验收**：复算脚本三个计数必须归零或给出豁免理由——尾标点 43→0（hero 类）、
半句收尾 17→0、不配对引号 4→0；抽帧前后对比；每条新规则**先在真实语料上量命中率再写**
（V32 的教训：不达标就不做，并把结论写下来）。

---

## V49 创意布局引擎：让 27 种讲法真的被用上（产品差异化）

**实测问题（311 拍）**
- 只用到 **21/27** 种；**6 种从未自动出现**：cards / compare / image / matrix / poster / showcase。
- 分布塌在文字上：**statement 138 拍 = 44.4%**，前 5 种（statement+title+summary+definition+list）
  = **249 拍 = 80%**。用户说的「只用那么一四五种」是准确的。
- 可达性查清：规则能产出 **22/27**；`image / poster / showcase` **只能手工选**
  （有模板、有 Modes 卡，但没有任何自动入口）。
- LLM 侧：`ALLOWED` 只给 **16 种**（`llm/planner.py:19-36`），且**提示词里没有任何多样性
  或配额要求**（5 条「硬性要求」全是正确性约束），`temperature=0.0` 下重复没有反作用力。
  候选池只有 `WEAK_KINDS={"statement"}`——即它只能改 statement，改不动已经误判成 list 的拍。

**关键调研结论（与用户设想不同，必须先说）**
> 没有任何一家被调研产品公开使用「情绪/实体 → 版式」的选择规则；业界用的是**结构信号**
> （列表/标题检测、长度、关键词与实体存在）——这正是我们规则已经在做的事。
> 因此差异化**不在更聪明的分类**，而在 ①全局版式配额 ②跨拍连续性 ③编排时序。

**要交付**
1. **版式族轮换预算**（planner 从逐拍变成整片视角）：统计连续同 kind 与各族
   （文字 / 数据 / 结构 / 素材）占比，硬约束「单 kind ≤35%、每片 ≥8 种、连续同 kind ≤3」，
   超预算时把可降级的拍换成形态更具体的 kind（枚举→cards、并列→compare、文件引用→poster）。
2. **给 3 个孤儿 kind 自动入口**：`poster`（检测到「据…报道 / 发言人表示 + 引号段」）、
   `showcase`（检测到多个界面/截图提及，或用户在 Studio 里上传多图时）、
   `image`（拍内提到「见图 / 如图所示」且有已上传素材）。
3. **组合版式**（真正的「花样」）：新增同屏双元素版式 `split`（文 + 图 / 文 + 数），
   让 quote+stat、diagram+caption 能同帧——这是 PPT 模板感与生成感的主要差别。
4. **候选池扩容**：LLM 可改写的来源从「只有 statement」扩到「statement + 误判风险高的 list/table」，
   并把配额作为提示词硬约束 + 越界回退（保留规则结果）。
5. 每条新映射都要在 43 作业上量命中率；不达标的**记为不做**（沿用 V32 的做法）。

**验收**：同一批真实文稿重跑分镜，报告三个数字——用到的 kind 数（21→≥26）、
statement 占比（44.4%→≤25%）、前 5 种占比（80%→≤55%）；且逐拍抽帧确认新形态没有把
文字挤出去（几何用 iframe 量矩形，不看缩略图）。

---

## V50 网页双语 zh / en（UI 系统性）

**实测问题**：`web/src` **零 locale 机制**（grep `i18n|locale|Intl|createContext|localStorage`
全部 0 命中）。中文字面量：App.tsx **62** 条、Studio.tsx **56** 条、modes.tsx **67** 条
（其中 54 条是模式名/描述，属内容不必翻）。另有硬伤：
- inspector 每个字段标签直接渲染 slot 键名（`Studio.tsx:599`）：`eyebrow / headline / gloss /
  x_axis …` 全是机器词；
- 状态徽章渲染原始枚举（`rules:numeric-ladder`、`succeeded`、`will_download`）；
- `CHECK_LABEL` 只覆盖 7 项而 `doctor.py` 出 9 项 → `llm` / `zh_tones` 漏成 snake_case；
- 日期是 `created_at.slice(5,16).replace("T"," ")`，无时区无 locale。

**要交付**：`web/src/i18n.ts`（单字典 + `useI18n` + 语言解析）；偏好持久化——注意
`brand.py:19/41/66` 是**闭集三键**存储，今天写 `ui_lang` 会被静默丢弃并在下次写入时清掉，
所以必须先扩 `_LABELS`（或新增 `/api/prefs`）；`html lang` 跟随切换（与 V53 的 SEO 联动）；
中英差异显式建模：字体栈、`letter-spacing`（英文才用 tracking）、行高 1.6→1.75、
按钮与 260px 侧栏在英文下的宽度、`Intl.NumberFormat/DateTimeFormat` 收口手写格式化。

**验收**：一条棘轮测试扫描「未走字典的用户可见字面量」，只准变少；两种语言下
820/1105/1400/2210 四档宽度 iframe 量矩形，溢出计数 0。

---

## V51 自适应布局与滚动盒审计（UI 简洁性 / 布局）

**实测问题**：全站只有**一条**断点（`@media (max-width:1100px)` 把三栏压成一栏）。
本轮刚修的节拍行塌陷是同一类问题的实例：`.beat` 同时是 flex 子项和 `overflow:hidden`，
自动最小尺寸归零 → 19 行全被压到 29px（内容 60px），滚动盒反而不滚（`listScroll 629 ==
listClient 629`）。这类塌陷在别处还会复发。

**要交付**：三档断点 + 面板折叠策略；把散落的 px 尺寸收进 token；**滚动盒审计**——所有
`overflow` 容器的直接子项一律 `flex:none`，并用一条 CSS 棘轮测试锁住；长文本在窄栏下的
截断策略统一（line-clamp 与 kind 标签共存，已有 `.beat-txt` 先例）；折叠态的键盘顺序复测。

**验收**：五档宽度（820/1000/1105/1400/2210）iframe 量矩形，溢出与塌陷计数为 0；
门禁见过它红（故意删一条 `flex:none` → exit 1，已做过一次）。

---

## V52 动效与可视化进阶：从「有动」到「编排」（动效 / 可视化）

**实测问题**：块级入场（`.inner > *`）用固定 `stagger: 0.09`，只在场景开头一小段里排完
（V34 已把**逐条/逐行**入场按停留时长摊开，所以「所有入场都挤在开头」这句原判断范围过宽，
2026-09-25 更正）；`base.html.j2` 曾有 4 处 `back.out(1.4–1.6)` 回弹，而 HyperFrames 的
`rules/spring-pop-entrance.md` 明写 bouncy `back.out` 是「agent 做 videos 的头号劝退特征、
绝不当默认」；每个 scene 是独立子树，**没有任何跨拍连续性**（所以转场只能 crossfade）。
~~stat 的 count-up 会因数字变宽抖动（缺 `tabular-nums`）~~ → **按证据作废**（见下面第 5 条）。

**要交付（按性价比排序）**
1. ✅ **去回弹（V52a 已做）**：`.node` / `.hub-mark` / `.kcard` / `.donut` 四处 `back.out` →
   `{{ eease }}`。四个主题的 `ease_enter` 本来就是 `power3.out`，正是该规则给的默认值，
   缩放幅度（0.82/0.7/0.94/0.86 → 1）不动，所以「弹」的感觉由前段速度承担而不是过冲。
   棘轮：`test_no_spring_overshoot_in_entrances_v52a` 渲染 flow/cycle/kpi/share 四 kind 的
   合成 HTML，出现 `back.out` 即红（改回一处见过它红）。
2. **line-mask 标题揭示 + 逐词错峰**（GSAP SplitText 的 `mask:"lines"` 机制，自己用
   overflow 包裹实现，S/M）——直接服务 80% 的纯文字拍；
3. **命名对象 morph**：给指标/节点稳定 id（`metric:转化率`、`node:感知`），相邻拍之间插值
   位置与尺寸而非交叉淡化（L，这是 PowerPoint Morph / Keynote Magic Move 的契约）；
4. **按速度匹配的接缝剪辑**：在运动峰值处切，按叙事关系（延续 / 换题 / 无关）选剪辑类型（M）；
5. ❌ **作废（V52a 实测，别再当活干）**：「hero 数字缺 `tabular-nums` 会抖动」。在真合成里
   量 `ExplainerCJK` @260px / 800 / letter-spacing −0.04em：**0–9 十个数字前宽完全一致
   （各 0.53em）**——等宽本来就是这个子集字的形状，count-up 无从横向抖动；而且该子集不含
   `tnum`，`font-variant-numeric: tabular-nums` 实测前后每个数字宽度一字不差，写了也是空操作。
   仍然值得做的只有「值域缩放字号 + 紧凑单位（3.2万 / 1.4亿）」这半条。
6. 每 kind 的入场签名表（哪个 kind 允许哪些动作），写进 VISUAL.md 并进确定性测试（M）。

**约束**：全部走 transform/opacity、compose 期算完几何、无运行时测量、无 `Math.random`
（确定性契约，见 VISUAL.md §2）。词级时间戳（karaoke 高亮）受限于本地 Kokoro 只给句长，
列为 M/L 并先做字符速率估算的过渡方案。

**验收**：逐拍抽帧 + contact sheet 全量看（不抽查）；`animation-map.mjs` 跑一遍看死区与错峰；
morph 要有「同一实体在两帧的位置/尺寸连续」的量测证据。

---

## V53 可维护性 / 遗留清理 / 文档 shuffle / SEO-Meta（代码质量）

**实测遗留（全部 grep 验证过零调用）**
- Python：`viz.py:114 _nums`、`sceneplan.py:80 tone_of`、`planner.py:50 ScenePlanner` 与
  `segment.py:51 Segmenter` 两个协议（只在各自 docstring 里被提）、`planner.py:17` 的
  re-export、`planner.py:590 plan_scenes`（只有测试用）；死字段
  `show_eyebrow_date / chunk_max_chars / track_index / fallback_kind`；
  `SentenceSegmenter.target_chars` 赋值后从未被读；`Captions.mode` 的 `"auto_chunk"`
  选项**根本没实现**（模板只判 `!= "none"`，与 `"sentence"` 表现完全相同）。
- CSS：约 **20 个**定义了但没有任何 .tsx 会产出的类（`.wordmark / .tagline / .rule / .hint /
  .studio / .rail / .wms / .result / .result-meta / .seg*（旧 stage pill 整块）/ .player /
  .check .name|found|fix|state / .dot.ok|.bad`）。
- 文档失真（可逐条核对）：`README.md:48`「Feature-complete through V5」（实际 V45+）、
  `README.md:12-13` 的阶段顺序与 `runner.py:29` 不一致；`ROADMAP.md` 标题写 V1–V8、
  as-of 2026-09-24、「12 kind」「16 个 kind」「7 项健康检查」（实际 27 kind / 9 项）、
  `:141` 把已交付的 matrix/arch/cycle/funnel 列为待办、`:143` 说 LLMPlanner 需要 API key
  （实际会探本地 Ollama）、`:144` 说「仓库非 git」（有 .git 且有提交）；
  `VISUAL.md` 里 26 卡 / 24 kind 是 `showcase` 之前的旧数；`VISUAL.md:56` 把根因写成
  不存在的 `segmenter` 模块（实为 `pipeline/segment.py`）。
- 计划文档自己也要吃自己的狗粮：`VISUAL.md:59-62` 说 warnings 是死数据
  （`ScenePlan.validate_against` 产出 → `save_plan` 入库 → 无端点返回 → 前端零消费），
  这条在 V53 一并补 API + UI，或明确删除该声明。

**要交付**
1. 删除上述死码（**删，不注释**），每删一处附 grep 证据；
2. `docs/` shuffle：README 重排为「跑起来 / 能力清单 / 架构 / 版本索引」，ROADMAP 归档为
   历史（V1–V8）并与本文件分工，VISUAL 只留视觉台账与落地记录，加一份 V47–V53 总索引；
3. SEO / Meta：`web/index.html` 现在只有 charset/viewport/theme-color/`title=Monoline`，
   `lang="en"` 写死——补 title 模板、description、OG/Twitter、canonical、robots、
   图标尺寸与 manifest，`lang` 跟随 V50 的语言；
4. 项目一致性机械化：kind↔模板 1:1（现在正好 27↔27）、Modes 目录↔KINDS（已有）、
   前端节拍计数↔后端 segmenter（用同一份实现或删掉前端估算）、`CHECK_LABEL`↔doctor 检查项，
   能断言的都进 `make test`。

**验收**：`make test` 绿且新增断言各自见过红；`grep` 死符号计数为 0；文档里每条 as-of
声明都能被代码反查。

---

## V55 LLM 分镜的真实约束是**墙钟**（可诊断性 / 产品可行性）
- 实测（本机 `batiai/gemma4-e4b:q4` @ Ollama）：解码 **0.3–0.85 字/秒**；89 字的极简 prompt 出 31 字用 36.4s，1106 字的骨架 prompt 出 70 字用 **224.4s**。也就是说 prompt 每多一千字要多花约 190 秒，而一拍真答案 ≈70 秒。
- 由此推翻 V41b/#112 的问题设定：**「升格几乎从不落地」不是模型判得差，是 12 拍/批必然撞 240s 超时**（实测 22 弱拍 → 2 批全失败 → `upgraded=0`），而 `merge` 又把空响应记成 `bad_kind=22`，把整整一轮调查指向了一个不存在的分类器 bug。
- 已落地：V55b 槽位预算从 `len()` 字符改成**显示单元**（汉字 1、拉丁 0.5，与版面一致）；V55c 提示词把每种 kind 写成可照抄的 **JSON 骨架**（模型随即给出了形状完全正确的 `list` 与 `compare`）；V55d `missing` 单列 + `_clean_slots` 返回具体原因 + 每批 12→3 拍 + 整轮 `MONOLINE_LLM_PLAN_SECONDS=150` 预算，超预算的批不问。
- 待做（顺序固定，别跳）：① **Studio 单拍「换个形状」按需请求**（一拍 ≈40–70s，用户主动触发、界面可见进度）——这是这台机器上唯一可行的模型参与方式；② 若仍要批量，先把系统提示词从 16 种 kind 裁到与纯文字拍相关的 5–6 种，砍掉约 600 字 prefill；③ 落地率稳定 >0 之后再谈按 `(script_hash, model)` 复用缓存。
- 判据教训（写进 VISUAL.md 台账）：空响应 ≠ 非法响应；「要 a/b，给了 ['a','b']」这类同义反复的错误文案会把人带偏一整轮，拒绝原因必须点名槽位与规则。

---

## 不做清单（附理由，避免以后重复讨论）

| 不做 | 理由 |
|---|---|
| 情绪/实体驱动选版式 | 调研的 14 家产品无一公开使用；结构信号才是业界通行做法，我们已有。差异化改投 V49 的配额 + V52 的连续性 |
| 无限/环境循环动效 | 与确定性逐帧渲染冲突（seek 必须可重复） |
| 图标覆盖率继续提升 | 已判定不再追：statement 37% 未匹配的 73 条逐条读过，多数无可映射名词 |
| 更聪明的分类器换掉规则 | `llm/planner.py:3-9` 的实测：全交给模型 83s、少回条目、改形槽位。规则掌结构、模型只补弱拍 |
| 再补几条修辞规则（对比 / 因果 / 跨度 / 序数 / 条件） | 2026-09-26 用 `backend/scripts/measure_shapes.py` 在 45 篇真稿 / 352 拍（**每作业只取最新一版 plan**）上量：statement 占 45.2%，其中对比 1.9%（唯一句子 **1**）、跨度 1.9%（2）、因果 1.3%（2）、序数 1.3%（2）、条件 **0%**。每类只有 1–2 个唯一句子，且命中的多是叙事散文（「他们也自知这样会使得自己的处境…」），写成规则就是 V32 已经否决过的假图示。**要提多样性只剩两条路**：模型逐拍参与（已上线，见 V55f）或内容无关的版式 treatment（已上线，见 V49） |

---

## 推进顺序与依赖

V48（标点契约）与 V47b（结构优先分批 + 滚动上下文）互不阻塞，可并行；
V49 依赖 V47b 的整片视角（配额需要跨拍上下文）；V52 的 morph 依赖 V49 的稳定实体 id；
V50 与 V51 互相依赖（英文宽度会暴露断点问题），建议同一轮做；
V53 穿插进行，但**文档 shuffle 放在最后**，否则前面的改动会让新文档再次失真。
