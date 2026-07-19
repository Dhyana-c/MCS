## Context

LoCoMo（ACL 2024, arXiv:2402.17753）提供 10 个虚构人物间的多轮对话（实测：每对话 19-32 会话、avg **27.2**、总 272 会话；avg **588** 轮/对话、总 5882 轮；avg **~18K token**/对话、总 ~182K token），配 1986 道 QA 题（V1）/ 1922 道（V2）。与 LongMemEval 的用户-助手模式不同，LoCoMo 是 **peer-to-peer 对话**——两个虚构人物互相聊天，信息来源平等。

**为什么 LoCoMo 而非直接跑 LongMemEval**：
1. 语料小：10 对话 × ~18K token = ~182K token 语料（对话记忆基准里最小）
2. 1986/1922 题覆盖 5 类能力，足够暴露问题
3. V2 修正版已下载，可直接使用
4. Mem0 92.5%、Zep 94.7%，有横向基线

**LoCoMo 不覆盖的能力**（由 LongMemEval 补）：
- Knowledge Update（信息被后续覆盖/失效）
- Abstention（对未提及信息诚实弃答）

## Goals / Non-Goals

**Goals:**
- 提供 `bench/locomo/`：LoCoMo V2 端到端对话记忆评测框架
- 数据拉取脚本：探测复用既有 clone，否则从 GitHub 克隆
- 数据三源合成：V2 base conversation + QA 主体，V2 caption 变体移植 VLM caption（按 dia_id，默认 moondream），V1 移植 evidence（按换名映射，98%）
- 对话式 ingest：每会话 = 一次 `mcs.ingest(IngestInput(content=拼接文本, timestamp=会话时间ISO, work_id=sample_id, metadata={doc_id, chunk_id}))`——双轨事件（当下 + 谈话中）
- 图隔离：每对话一个独立 SQLite db（work_id 用于启用 ③b，非隔离）
- 评测双轨（同一套图）：检索 Recall@k（移植 evidence 的 1881 题，session 级）+ QA 正确率（V2 全部 1922 题，LLM judge）
- 按类型分项指标，重点看 temporal / adversarial / single-hop
- 框架 ingest 建图 + agent 查询评测

**Non-Goals:**
- 不实现 LoCoMo 的 event summarization 和 multimodal dialogue generation 任务（只做 QA）
- 不改造 MCS 核心代码（temporal 所需的锚点解析由**独立框架 change `work-event-anchor-resolution`** 承担，本 change 声明依赖，见 D11）
- 不追求 SOTA 排名；目标是暴露 MCS 在对话记忆场景的能力边界
- 不处理 LoCoMo 的多模态部分（不下载/识别图像；用 V2 caption 变体的 VLM caption 文本替代，死链 76 轮无 caption 如实失分）
- LongMemEval 评测由独立 change `longmemeval-bench` 负责
- 不修改 `bench/agent_build.py` 共享模块（只复用 resume 思路，不改动代码）

## Decisions

### D1: 三源合成——V2 为主体，caption 取 V2 VLM 变体，V1 只剩 evidence 移植

**选择**：以 **V2 base conversation + QA 为唯一主体**（建图语料、评测问题都用 V2）；另移植两样东西：
1. **caption（取 V2 caption 变体，V1 BLIP 弃用）**：V2 base 无 caption（实测 910 带图轮 caption 全空）。V2 仓库另提供三个 **VLM caption 变体**（`locomo_v2_{qwen,moondream,minicpm}.json`），实测其 conversation 文本与 base **逐轮零差异**、caption 覆盖 834/910（缺失 76 轮为死链图像），可按 `dia_id` 直接移植。**默认 `moondream_caption`**（OCR 在线且最短：avg 438 字符/图 vs qwen 982；对 ingest 成本最友好），config 可切换。V1 的 `blip_caption` 无 OCR 能力（实测同图对比：BLIP "a photo of a dog walking past a wall" vs moondream OCR 出壁画上 "Tran[sgender]" 标语文字）、且带 V1 语境，弃用。
2. **`evidence`**：V2 QA 无 evidence 字段（**V2 有意删除**，见下）。按**换名映射**把 V1 evidence 移植到 V2 题上，仅作诊断用途（见 D5 / Risks）。

**关键发现一（V2 是"去污染换名版"）**：V2 不只修正答案——**10/10 对话把人物全部换名**（Caroline→Sarah、Melanie→Jessica……），conversation 文本 2072 处 turn 改动全部是人名替换。V2 的 `DECONTAMINATION_ROADMAP` 明确动机：**中和 LLM 预训练记忆污染**（LoCoMo V1 已流入预训练语料），换名迫使被测系统依赖真实检索而非模型权重背答案。对本评测的意义：
- **用 V2 才能证明 agent 的答案来自图检索**（agent 的 LLM 大概率见过 V1）——这是"V2 为主体"最硬的理由，比答案修正更根本
- **绝不能混用 V1 问题查 V2 语料建的图**（问 Sarah 的图里只有 Caroline，检索必然失败）——旧方案"检索轨用 V1 source"存在此隐藏 bug，废弃
- 换名映射可从两版 `speaker_a/b` 字段**机械建立**（每对话 2 个名字），无需 LLM
- 移植方法：V1 问题文本经换名映射替换后与 V2 问题**精确匹配**（大小写不敏感），命中者把 V1 `evidence` 挂到 V2 题上。实测 **1881/1922 = 98%** 命中；未命中的 41 题只走 QA 轨
- V2 放弃了时间平移（roadmap 记录"Temporal shifting aborted"）——**日期保持原始**，temporal 评测不受去污染干扰

**关键发现二（V1 evidence 的真实缺陷是 Multi-Mention Flaw）**：V2 删除 evidence（1923 处）是**有意为之**——V1 的 evidence 只标注事实**首次提及**的 `dia_id`，同一事实在后续 session 重提时，检索到重提处的系统被 R@K 脚本误判 0 分。V2 因此主张端到端 LLM-judge 为唯一官方口径。本评测的检索轨（session 级 + any-hit）缓解了同 session 重提，但**跨 session 重提仍会误判 miss**——检索轨定位为**诊断性副指标**（区分"没检索到"vs"没答对"），不与外部系统对比。

**理由**：
- V1 有 99 个 ground-truth 幻觉 + Multi-Mention Flaw + epistemic honesty 惩罚问题；V2 修正答案 + 去污染，是 QA 评测的正确数据源
- evidence / caption 的 `dia_id` 是结构标识，与人名无关，跨版本移植安全（dia_id 集合已验证一致）

### D2: 数据拉取流程

**选择**：优先探测复用本机既有 clone，否则从 GitHub 克隆。

**探测复用**：当前两个仓库已 clone 在 `bench/longmemeval/data/locomo_repo` 与 `bench/longmemeval/data/locomo_v2`（历史原因落在 longmemeval 目录下）。`download_data.py` 先探测该位置，存在且校验通过则**复制**（copy 而非 move——`longmemeval-bench` 是未 apply 的姊妹 change，可能仍引用旧位置，copy 不破坏它）到规范位置 `bench/locomo/data/`，不重复下载。

```bash
# V1 官方数据
git clone --depth 1 https://github.com/snap-research/locomo.git bench/locomo/data/locomo_repo

# V2 社区修正版
git clone --depth 1 https://github.com/BrianV1981/locomo-v2.git bench/locomo/data/locomo_v2
```

**V2 checkout 问题**：locomo-v2 仓库含 Windows Zone.Identifier 文件，`git checkout` 会失败。需在 clone 后手动 restore：
```bash
git clone --depth 1 https://github.com/BrianV1981/locomo-v2.git bench/locomo/data/locomo_v2
cd bench/locomo/data/locomo_v2 && git restore --source=HEAD :/ 2>/dev/null || true
```

**数据文件位置**：
- V1: `bench/locomo/data/locomo_repo/data/locomo10.json`（2.8MB，10 对话，1986 题）
- V2: `bench/locomo/data/locomo_v2/data/locomo_v2_base.json`（2.5MB，10 对话，1922 题）
- V1 source: `bench/locomo/data/locomo_v2/data/locomo_v1_source.json`（2.8MB，含 evidence）

**数据不入 git**：`.gitignore` 排除 `bench/locomo/data/locomo_*/`。

### D3: 对话式 ingest——每会话一次 ingest，`work_id` 启用双轨事件

**选择**：每个会话（session_N）拼接为一段文本，调 `mcs.ingest(IngestInput(content=拼接文本, timestamp=会话时间ISO, work_id=sample_id, metadata={"doc_id": sample_id, "chunk_id": "session_N"}))`。会话按时间顺序依次 ingest。

**双轨事件（universe 设计动机的直接应用）**：`work_id=sample_id` 使每对话自成 universe，一次 ingest 产生两类事件，正好对应 LoCoMo 的两类时间：

| | 产生方式 | universe / 时间轴 | LoCoMo 对应 |
|---|---|---|---|
| **当下事件**（摄入行为） | 规则、不经 LLM | `__reality__`，timestamp=会话时间 | "5 月 8 日这场对话发生了" |
| **谈话中的事件**（叙述发生） | ③b `extract_work_events` LLM 抽取 | 对话 universe，narr_timestamp=事发时间 | "Caroline 5 月 7 日去了互助会" |

temporal 题问的全部是第二类（"When did Sarah go to the support group?" → 7 May 2023），由对话 universe 的叙事时间轴（`timeline` 工具 / `narrative_timeline`）回答。相对时间（"yesterday"）→ 绝对日期的解析依赖配套 change `work-event-anchor-resolution`（见 D11）；锚点（`[1:56 pm on 8 May, 2023]`）就在拼接文本每行里，LLM 抽取时可直接推理。
`metadata` 里的 `doc_id`/`chunk_id` 供 source_tracking 记录 session 级溯源（检索轨用，见 D5）。

**拼接格式**（peer-to-peer 模式，两方平等）：
```
[1:56 pm on 8 May, 2023] Sarah: Hey Jess! Good to see you!
[1:56 pm on 8 May, 2023] Jessica: Hi Sarah! How have you been?
[1:57 pm on 8 May, 2023] Sarah: I went to a LGBTQ support group yesterday...
[1:57 pm on 8 May, 2023] Jessica: [shared image: a photo of a bowl with a black and white flower design]
```

**时间戳**：`IngestInput.timestamp` 为 ISO 8601 字符串。解析 `"1:56 pm on 8 May, 2023"` → `datetime(2023, 5, 8, 13, 56)` → `.isoformat()` = `"2023-05-08T13:56:00"`（该格式实测全量 272 会话 0 解析失败）。

**有意为之**：将 `timestamp` 回填为会话时间，使摄入行为事件（当下事件）的时间戳 = 对话发生时间，而非实际 ingest 时间。这令 `__reality__` 时间轴反映对话时序而非 ingest 时序。宪法"摄入事件记录这一行为"的语义在此为"记录这一对话发生"，与 `timestamp` 字段的设计意图一致。

**理由**：
- 会话粒度是 LoCoMo 的自然分割点，与双轨事件设计对齐
- 按时间顺序 ingest 保证当下事件时间戳递增；叙事事件时间由 ③b 独立抽取
- 图像用 V2 caption 变体移植的 VLM caption 替代（URL 大部分已 404，见 D1）

**备选**：每轮对话一次 ingest → 粒度过细、事件节点爆炸、成本高
**备选**：整个对话一次 ingest → 丢失会话时间边界、时间轴退化

### D4: 图隔离——每对话一个独立 db；`work_id` 的作用是启用 ③b，不是隔离

**选择**：每个 LoCoMo 对话（sample_id）创建独立 SQLite db（`locomo_{sample_id}.db`）。**同时传 `work_id=sample_id`**——不是为了隔离（独立 db 已保证），而是为了：
1. **启用 ③b 作品叙事事件抽取**（仅 `work_id` 非空时触发）——temporal 题的答案来源（见 D3 双轨事件）
2. 每对话自成 universe：概念/事实/叙事事件归对话 universe，参与者名限同 universe 解析；摄入行为事件固定 `__reality__`——两条时间轴天然分离，`timeline(universe=对话)` 查叙事、不混入摄入记录
3. 语义上也正确：LoCoMo 对话是虚构人物的"作品"，按宪法归 work universe 而非现实

**理由**：LoCoMo 的 10 个对话是不同人物对，记忆不应跨对话泄漏。独立 db 保证完全隔离，且可并行评测不同对话。

**备选（废弃）**：共享一个 db + 靠 universe 隔离 10 个对话 → 理论可行（universe 已隔离合并/互斥/聚类），但所有孤儿挂同一 `__seed_root__`、查询守门需处处传 universe，复杂度高而无语义收益；独立 db 更简单且可并行。
**备选（废弃）**：不传 `work_id`、全按 `__reality__` → 隔离不受影响，但 ③b 不触发、谈话中的事件不落叙事时间轴，temporal 题失去答案来源——放弃 universe 能力面的主战场。

### D5: 评测双轨——检索 + QA

**选择**：
- **检索轨**（移植 evidence 的 1881 题，见 D1；问题与图同用 V2 人名）：`mcs.query(question)` → 返回节点 → 经 source_tracking 判 evidence 对应**会话**是否被检索到 → Recall@k（session 级）
- **QA 轨**（V2 全部 1922 题）：agent.chat(question) → LLM 生成答案 → LLM judge 判对错 → 按类型分正确率

**检索轨映射（session 级，非 turn 级）**：
- ingest 时经 `IngestInput.metadata` 传 `doc_id=sample_id, chunk_id="session_N"`（source_tracking 插件消费 kwargs 同域的 metadata，multihop 同款用法）→ 每个节点的 `source_tracking.sources` 带其来源 session
- evidence 中的 `dia_id`（如 `"D1:3"`）→ 提取 session 编号（`D1` → session_1）→ 判召回节点 sources 的 `chunk_id` 是否覆盖该 session
- **session 级而非 turn 级的理由**：每会话一次 ingest 下，该次抽出的所有节点共享同一 `chunk_id`——turn 级溯源需每 turn 一次 ingest（事件节点爆炸、破坏会话粒度时间轴）或改框架 source 切分，都不值得。session 级已够用：evidence 的 `D{N}` 前缀本身就是 session 标注，且每 session 平均 ~22 轮，粒度合理。
- **Recall@k 定义**：k=5,10,20；命中 = evidence session 中**至少一个**被检索到（any-evidence hit）；同时报 all-evidence 命中率。

**QA 轨主指标 = LLM-judge 正确率**（对齐 Mem0/Zep 口径），F1 为副指标。

### D6: 建图路径——框架 ingest，agent 查询

**选择**：建图走框架 `mcs.ingest()`，查询评测走 agent 路径（`mcs_agent`）。框架 `mcs.query()` 作为消融对照。

**理由**：
- LoCoMo 每对话 ~18K token / ~27 会话，图很小，框架 ingest 足够；且对话会话必须**全量按时序**入图，没有 agent 建图的决策空间（multihop 的 agent 建图价值在写入取舍与修图，此处不存在）
- agent 建图是 multihop 609 篇大语料才需要的（探索+纠错循环）
- 查询评测走 agent：multihop 已证 agent 优于框架 BFS，对话记忆场景更需要 agent 的工具组合能力（timeline 查时间轴 + search 查关联 + merge 修互斥）
- **不修改 `bench/agent_build.py`**：只复用 resume 思路（检查 db 文件是否存在），不改动共享模块代码

### D7: adversarial 类弃答判定——交 LLM judge

**选择**：adversarial 题（category 5）的弃答判定交 LLM judge，不用关键词匹配。

**理由**：agent 可能答 "Sarah never discussed that" / "The conversation doesn't mention this about Sarah"——关键词匹配（"not mentioned"/"don't know"）会漏判。LLM judge 统一处理所有类型的判定，口径一致。judge prompt 需明确：adversarial 题的正确答案 = "该人物未提及此信息"，答具体内容（尤其是 adversarial_answer）= 错误。

**与黄金笼互补**：
- 黄金笼：语料中无相关文档 → 检索不到 → 弃答
- LoCoMo adversarial：有相关内容但归属错误 → 需识别归因错误 → 弃答

### D8: 预处理缓存

**选择**：首次加载后序列化预处理结果到 `bench/locomo/data/preprocessed/`，后续加载直接读取缓存。

**理由**：V1/V2 JSON 文件共 ~8MB，每次加载+解析时间戳较慢。缓存后加载时间从秒级降到毫秒级。

### D9: 类别映射（从实测数据钉死）

**选择**：从 V1 source 实测数据确认的类别映射：

| Category | 名称 | 语义特征 | V1 数量 | V2 数量 | 评测指标 |
|----------|------|---------|---------|---------|---------|
| 1 | **multi-hop** | 跨 session 证据（evidence 含多个 D{N}） | 282 | 261 | LLM-judge 正确率（副：F1 逗号分割） |
| 2 | **temporal** | 答案含时间/日期（"7 May 2023"/"2022"/"The sunday before 25 May 2023"） | 321 | 308 | LLM-judge 正确率（副：F1 + 时间偏移容忍单列） |
| 3 | **open-domain** | 推理/偏好（答案含 "Likely no"/"Yes, since..."） | 96 | 94 | LLM-judge 正确率（副：rubric 评分） |
| 4 | **single-hop** | 单证据点（evidence 仅一个 D{N}:M，答案短） | 841 | 821 | LLM-judge 正确率（副：F1） |
| 5 | **adversarial** | 错误归因（有 adversarial_answer，正确答案 = 弃答） | 446 | 438 | LLM-judge 弃答判定 |

**注意**：V2 总量 1922（非 1986），V1 总量 1986。V2 修正导致部分题被删除/合并。Cat 4 是最大类（~841/821），语义为 single-hop 而非 inference——之前标错。

### D10: 成本估算（基于 golden_cage 实测）

**选择**：按 golden_cage 实测单位成本重估。

**golden_cage 实测**：
- 框架 ingest：~11K prompt + ~1.5K completion / 次（141 次调用）
- agent query：~49K prompt / 题（29.8 次调用，含 navigate_hub + select_facts）

**LoCoMo 重估**（会话数实测 272，非 252）：
- Ingest：272 会话 × ~7K token/次（extract_concepts + judge_relations + **extract_work_events**（work_id 多一次调用）+ 守门）= **~2M token**
- Agent QA：1922 题 × ~22K token/题（图更小，探索步数更少）= **~42M token**
- LLM judge：1922 题 × ~2.5K token = **~5M token**
- 框架 query 对照（检索轨）：默认**抽样**每对话 30 题（~300 题 × ~8K）= ~2.4M；全量 1881 题 ~15M 按需
- **合计 ~51M token**（原估 800K 低了 60+ 倍）

**执行策略**：先跑单对话 conv-26（194 题，~5M token）验证全链路（含 ③b 叙事事件质量、timeline 可用性），确认单位成本后再决定全量。支持 `--max-conversations N` 限制对话数。

### D11: temporal 依赖链——③b 叙事事件 + 锚点解析 + timeline

**背景（实测）**：temporal 题 71%（228/321，V1 口径）的证据原文含相对时间表达、gold 答案是解析后的绝对日期（"went ... yesterday"（会话 5 月 8 日）→ "7 May 2023"；"two days ago"（7 月 12 日）→ "10 July 2023"；"last year"（2023）→ "2022"）。宪法 real-narrative-events 规则把相对时间从命题里剥掉（去时间化）、归事件层——**答案所需的日期只能活在叙事事件的 `narr_timestamp` 里**。

**依赖链**（三环，缺一 temporal 不通）：
1. **③b 触发**：`work_id=sample_id`（D3/D4）→ `extract_work_events` 从会话文本抽"谈话中的事件"
2. **锚点解析**：配套 change `work-event-anchor-resolution`——现行 prompt 规定 `narr_timestamp` "保留原文形态、不换算"（防"建安五年"式幻觉换算），会把 "yesterday" 原样抽出；而排序（`timestamp_sort_value`）仅认 ISO / 数字年，"yesterday" 垫底不可排、"7 May 2023" 被数字年误解析成 7。配套 change 放宽为：**文本内含显式时间锚点时（拼接文本每行自带 `[1:56 pm on 8 May, 2023]`），相对时间 MAY 解析为 ISO 绝对时间**；无锚点行为不变。这等于把宪法预留的"Phase 2 纪年归一化"的"锚点在场"子集提前落地
3. **查询侧**：agent `timeline(universe=对话)` 查叙事时间轴回答（agent prompt 提示 temporal 题优先用 timeline 工具）

**评测意义**：配套 change 落地前后各跑一次 temporal 子集，可直接度量该能力的贡献（bench 度量框架改进，正是分层的价值）。

## Risks / Trade-offs

- **[LoCoMo 是虚构对话]** 两个虚构人物间的对话 ≠ 真实用户记忆场景。但作为标准化评测，可控性更强，且 Mem0/Zep 都用它对标，横向可比。虚构人物按宪法归 work universe（D4），语义自洽
- **[evidence 移植覆盖 98%]** 41/1922 题换名匹配不中（V2 对问题文本另有改写）→ 这些题只走 QA 轨，检索轨样本 1881 题
- **[Multi-Mention Flaw]** V1 evidence 只标事实**首次提及**处（V2 因此整体删除 evidence、主张端到端 judge）→ 跨 session 重提的事实被检索到时会误判 miss，session 级 Recall 系统性偏低。检索轨仅作**诊断性副指标**（定位"没检索到 vs 没答对"），MUST NOT 与外部系统对比、MUST NOT 进主表
- **[temporal 依赖配套 change]** D11 依赖链任何一环缺失（③b 抽取质量不足 / 锚点解析未落地 / agent 不调 timeline），temporal 类都会失分。配套未落地前跑评测，temporal 如实反映缺口（71% 题受影响）——这本身是有价值的基线
- **[③b 抽取质量未知]** `extract_work_events` 此前在小说语料上验证，对话语料（口语、碎片化、"0-5 事件/段"约束 vs 会话 ~22 轮）的抽取质量未实测 → conv-26 试点重点观察
- **[adversarial 类归因判定]** MCS 的互斥边可能把错误归因的信息标记为互斥而非"未提及"→ 需观察实际行为
- **[CC BY-NC 4.0 许可]** LoCoMo 仅限非商业使用，学术评测合规
- **[图像死链残留]** 910 带图轮中 76 轮无 caption（对应永久死链图像，V2 官方判定依赖它们的 63 题不可解）→ 这些题会失分，报告单列不计入能力结论；其余 834 轮用 VLM caption（含 OCR），多模态降级为文本评测但关键视觉事实保留
- **[peer-to-peer 角色差异]** LoCoMo 两方平等，无"用户/助手"区分 → agent 需理解"问关于 Sarah 的事"vs"问关于 Jessica 的事"
- **[成本]** 全量 ~51M token，先跑 conv-26 单对话（~5M）验证

## Open Questions

- agent prompt 是否需要针对 LoCoMo 的 peer-to-peer 对话模式做特殊适配（vs 用户-助手模式）
- ③b 对口语对话文本的"0-5 个/段"抽取密度是否够（一个 ~22 轮会话可能含多个值得记的发生）——conv-26 试点后定
- 41 题无 evidence 的检索轨缺口是否需要人工补标（倾向不补，样本已够）
