## Context

LongMemEval（ICLR 2025, arXiv:2410.10813）是面向长期对话记忆的评测基准，500 道人工构造题，语料为多轮用户-助手对话历史。与 LoCoMo（peer-to-peer 虚构对话）不同，LongMemEval 是**用户-助手**模式——更接近 MCS 的目标场景（个人记忆系统）。

**核心差异 vs LoCoMo**：
- **Knowledge Update**（78 题）：用户信息随时间变化（如换了工作、更新了偏好），需识别最新值、标记旧值失效——正面打互斥边
- **Abstention**（30 题）：问题基于错误前提（用户从未提及 X），需诚实弃答——正面打 null 口径
- **User-Assistant 模式**：助手信息是"被提及的信息"而非"用户记忆"，角色不对称
- **每题独立历史**：500 题各有独立的对话历史，需图隔离

**三个版本**：
- Oracle（15MB）：每题仅含证据会话（1-6 个，avg 1.9），~6.6K token/题
- S（277MB）：每题含证据 + ~45 个填充会话，~115K token/题
- M（1.69GB）：每题含证据 + ~495 个填充会话，~1.5M token/题

**Oracle 版成本估算**（基于 golden_cage 实测重估）：
- Ingest：500 题 × avg 1.9 会话 = ~950 次 ingest × ~6K token/次 = **~5.7M token**
- Agent QA：500 题 × ~22K token/题 = **~11M token**
- LLM judge：500 题 × ~2.5K token = **~1.25M token**
- **合计约 ~18M token**，可控

**S 版成本估算**：
- Ingest：500 题 × ~48 会话 × ~6K token/次 = **~144M token**
- Agent QA + judge：同 Oracle ~12M token
- **合计约 ~156M token**，成本高，留 Phase 2

## Goals / Non-Goals

**Goals:**
- 提供 `bench/longmemeval/`：LongMemEval 端到端对话记忆评测框架
- 数据拉取脚本：从 HuggingFace 下载 oracle / S 版数据
- 数据预处理：解析时间戳、拼接对话、按类型拆分
- 对话式 ingest：每会话 = 一次 `mcs.ingest(IngestInput(content=对话文本, timestamp=ISO时间戳))`
- 图隔离：每题一个独立 SQLite db
- 评测双轨：检索 Recall@k + QA 正确率（LLM judge）
- 按类型分项指标，重点看 knowledge-update / temporal-reasoning / abstention
- Oracle 版首期，S 版 Phase 2

**Non-Goals:**
- 不跑 M 版（1.69GB，成本过高）
- 不改造 MCS 核心代码
- 不追求 SOTA 排名；目标是暴露 MCS 在对话记忆场景的能力边界
- 不实现 LongMemEval 的检索增强生成（RAG）评测模式——只做端到端 QA

## Decisions

### D1: Oracle 版首期，S 版 Phase 2

**选择**：首期用 Oracle 版（每题仅证据会话，~6.6K token/题），S 版留 Phase 2。

**理由**：
- Oracle 版 ingest 成本 ~15M token，可控
- Oracle 版已包含所有 500 题和 6 种类型，能力覆盖完整
- Oracle 版无填充会话干扰，更直接测"证据是否被正确记忆和检索"
- S 版的填充会话测试"大海捞针"能力，是更高难度的挑战，留 Phase 2

**风险**：Oracle 版无干扰会话，可能高估检索能力。S 版结果可能显著下降。

### D2: 每题一个独立 db

**选择**：每个 LongMemEval 问题（question_id）创建独立 SQLite db（`longmemeval_{question_id}.db`）。

**理由**：
- LongMemEval 每题有独立的对话历史，记忆不应跨题泄漏
- 与 Mem0/Zep 的评测方式一致（每题独立 user_id）
- Oracle 版每题仅 1-6 个会话，图极小，建图快

**备选**：共享图 + universe 隔离 → 理论可行但 500 个 universe 管理复杂，且每题历史完全独立，共享无语义收益

### D3: 对话式 ingest——每会话一次 ingest

**选择**：每个会话拼接为一段文本，调 `mcs.ingest(IngestInput(content=拼接文本, timestamp=ISO时间戳))`。会话按时间顺序依次 ingest。

**拼接格式**（user-assistant 模式）：
```
[2023-04-10 17:50] user: I just bought a new Toyota Camry last week!
[2023-04-10 17:50] assistant: Congratulations on your new car! How are you liking it so far?
[2023-04-10 17:51] user: It's great, but I noticed the GPS system isn't working correctly...
```

**时间戳**：`IngestInput.timestamp` 为 ISO 8601 字符串。解析 `"2023/04/10 (Mon) 17:50"` → `datetime(2023, 4, 10, 17, 50)` → `.isoformat()` = `"2023-04-10T17:50:00"`。

**有意为之**：将 `timestamp` 回填为会话时间，使摄入行为事件的时间戳 = 对话发生时间。这令事件节点的时间轴反映对话时序而非 ingest 时序——对 temporal-reasoning 评测至关重要。

**理由**：
- 每次 ingest 自动产生一个事件节点，天然形成用户时间轴
- 会话粒度是 LongMemEval 的自然分割点
- 按时间顺序 ingest 保证事件节点时间戳递增
- user/assistant 角色标注保留语义，LLM 抽取时可区分"用户说的"和"助手说的"

### D4: 评测双轨——检索 + QA

**选择**：
- **检索轨**：`mcs.query(question)` → 返回节点 → 检查 answer_session_ids 对应的会话内容是否在返回节点中 → Recall@k（session 级，k=5,10,20；any-evidence hit + all-evidence hit）
- **QA 轨**：agent.chat(question) → LLM 生成答案 → LLM judge 判对错 → 按类型分指标

**检索轨映射（session 级，经 source_tracking）**：
- ingest 时经 `IngestInput.metadata` 传 `doc_id=question_id, chunk_id=haystack_session_id`（LongMemEval 会话自带 id，如 `"answer_4be1b6b4_2"`，比 LoCoMo 的 `session_N` 更自然）→ 节点 `source_tracking.sources` 带来源会话
- 召回节点按 rank 序取 `chunk_id` 去重保序 → 与 `answer_session_ids` 比对
- Recall@k 命中定义：any-evidence hit（至少一个 answer_session 被检索到，主）+ all-evidence hit（副）；k=5,10,20

**QA 轨主指标 = LLM-judge 正确率**（对齐 LoCoMo bench 与 Zep 报告口径；LongMemEval 官方评测本身即 GPT judge），F1 为副指标单列。judge 判定按类型定制：
- temporal-reasoning：judge 判语义等价；副指标 F1 + 时间偏移容忍（单列不进主表）
- multi-session：judge 判语义等价（32 个 int 计数题 judge 判数值相等）
- knowledge-update：judge 只认**最新值**（答旧值 = 错误）
- single-session-*：judge 判语义等价
- single-session-preference：judge 按 rubric 评分（答案 avg 390 字符是评分标准而非短答案）
- abstention：judge 判弃答语义（见 D8）

### D5: 建图路径——框架 ingest，agent 查询

**选择**：建图走框架 `mcs.ingest()`，查询评测走 agent 路径（`mcs_agent`）。框架 `mcs.query()` 作为消融对照。

**理由**：
- Oracle 版每题仅 1-6 个会话，图极小，框架 ingest 足够
- 查询评测走 agent：knowledge-update 题需要 merge/互斥工具，temporal-reasoning 题需要 timeline 工具
- 框架 query 作为消融对照，量化 agent 工具组合的增益
- **不修改 `bench/agent_build.py`**：只复用 resume 思路（检查 db 文件是否存在），不改动共享模块代码

### D6: 数据拉取与预处理流程

**选择**：实现 `scripts/download_data.py` + `data.py` 中的预处理逻辑。

**拉取流程**：
```bash
# Oracle（已下载）
wget https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json

# S 版（Phase 2）
wget https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json
```

**预处理**：
1. 加载 JSON → 解析每题的 haystack_dates / haystack_sessions / answer_session_ids
2. 时间戳解析：`"2023/04/10 (Mon) 17:50"` → `datetime(2023, 4, 10, 17, 50)`
3. 会话排序：按 haystack_dates 升序
4. 按类型拆分问题（6 类 + abstention 子集）
5. 输出预处理后的数据文件（可选，加速后续加载）

### D7: knowledge-update 类的特殊处理

**选择**：knowledge-update 题的评测标准为"答案是否为最新值"。

**理由**：这类题测试的是"用户信息随时间变化后，系统能否识别最新值"。旧值在图中应被互斥边标记为失效。若 agent 回答旧值 = 错误，回答最新值 = 正确。这直接暴露互斥边 + arbitrate 的正确性。

**风险**：若互斥机制未正确触发（旧值未被标记失效），knowledge-update 准确率会显著偏低——这恰好是评测要暴露的问题。

### D8: abstention 类的特殊处理

**选择**：abstention 题（question_id 以 `_abs` 结尾）的正确答案 = 弃答（"I don't know" / "Not mentioned in the history"）。

**理由**：这类题基于错误前提（用户从未提及 X），测试系统是否会幻觉出答案。与黄金笼的 null_query 互补：
- 黄金笼：语料中无相关文档 → 检索不到 → 弃答
- LongMemEval abstention：用户历史中未提及 X → 但问题看起来合理 → 需主动判断"未提及"而非幻觉

**评测**：abstention 题弃答判定交 LLM judge（不用关键词匹配）。agent 可能答 "The user never mentioned anything about X"——关键词匹配会漏判。judge prompt 需明确：abstention 题的正确答案 = "用户历史中未提及此信息"，答具体内容 = 错误。

## Risks / Trade-offs

- **[Oracle 版无干扰]** 无填充会话，检索可能偏容易 → S 版结果可能显著下降，需注明版本差异
- **[每题独立图成本]** 500 次建图 × ingest LLM 开销 → Oracle 版约 ~18M token 可控，S 版 ~156M token 较贵
- **[knowledge-update 依赖互斥]** 若互斥机制有 bug，78 题直接暴露 → 这正是评测目的
- **[temporal-reasoning vs 去时间化]** real-narrative-events 规则规定相对时间转述去时间化，LongMemEval temporal 题依赖"相对时间 + 会话日期"解析——框架层能力边界，本 bench 如实反映。**注意与 LoCoMo 的路线差异**：LoCoMo 是虚构对话、传 `work_id` 走 ③b 叙事事件 + `work-event-anchor-resolution`（改 `extract_work_events` prompt）；而 LongMemEval 是**真实用户-助手历史**，按宪法归 `__reality__`、不传 `work_id`、③b 不触发——anchor-resolution **帮不到这里**。temporal 路线三选一（Open Question，实现前定）：(a) 也传 `work_id=question_id` 把每题历史当"作品"（机制可行、能吃 ③b + anchor-resolution，但语义牵强——用户历史不是虚构作品）；(b) 把锚点解析扩展到 `extract_concepts` 的历史事实路径（"last week" + 会话日期 → 绝对日期留命题 content，符合宪法"带固定历史时间抽历史事实命题"；框架 change 范围扩大）；(c) 不修，如实失分作为基线。
- **[preference 类 rubric 评分]** 答案是评分标准（avg 390 字符）而非短答案，LLM judge 需按 rubric 评分，比其他类型更复杂
- **[int 答案]** 32 个 multi-session 题的答案是整数（计数题），需特殊处理数字匹配
- **[时间戳格式]** `"2023/04/10 (Mon) 17:50"` 需自定义解析，非标准 ISO 格式

## Open Questions

- **temporal 路线三选一**（见 Risks，实现前定）：work_id 化 / 锚点解析扩展到 real-narrative-events / 如实失分基线
- Oracle 版是否足够暴露问题，还是必须跑 S 版才有区分度
- preference 类的 rubric 评分，judge prompt 是否需要特殊设计（vs 短答案的语义等价判定）
- 每题独立图是否需要持久化（评测完即删 vs 保留供分析；500 个小 db 文件管理）
- agent prompt 是否需要针对 knowledge-update 类做特殊引导（"注意信息可能已更新"）
