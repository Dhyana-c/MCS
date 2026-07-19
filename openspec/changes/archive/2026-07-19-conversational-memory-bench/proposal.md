## Why

MCS 已在 multihop-rag（新闻语料、文档级检索）和 golden_cage（null 诚实口径）上验证了核心图引擎的检索能力。但这两个评测共享同一盲区：**语料是静态文档、无时间维度、无信息更新/覆盖、无用户-助手对话形态**——而 MCS 的**双轨事件模型（当下事件 vs 谈话中的事件）**、universe 时间轴、互斥裁决、agent 工具（timeline/search/merge）恰恰是为"长期对话记忆"设计的。

LoCoMo（ACL 2024, arXiv:2402.17753）是面向长期对话记忆的评测基准，几乎为 MCS 的能力面定制：

| 能力 | LoCoMo 题型（V2 实测数量） | MCS 对应 |
|------|-----------|---------|
| 时间推理 | temporal（category 2，308 题） | ③b 叙事事件层 + universe 时间轴 + timeline 工具 |
| 错误归因检测 | adversarial（category 5，438 题） | null 诚实口径 + 互斥边 |
| 跨会话推理 | multi-hop（category 1，261 题） | BFS 语义游走 + agent 探索 |
| 单点事实 | single-hop（category 4，最大类 821 题） | 基础检索 |
| 开放推理 | open-domain（category 3，94 题） | 概念网络覆盖度 |

**temporal 正中 universe 设计动机**：实测 71% 的 temporal 题依赖相对时间解析（证据原文 "went to support group *yesterday*"（会话 5 月 8 日）→ gold 答案 *7 May 2023*）。这正是双轨事件要区分的两类时间——**当下事件**（"这场对话 5 月 8 日发生了"：摄入行为事件，规则产生、落 `__reality__` 时间轴）vs **谈话中的事件**（"Caroline 5 月 7 日去了互助会"：③b `extract_work_events` LLM 抽取、落对话 universe 独立叙事时间轴）。评测按 `work_id=对话id` 走 ③b，temporal 题由叙事时间轴回答（依赖配套框架 change，见 Capabilities）。

**LoCoMo 优先的理由**：
1. 语料小：10 对话 × ~18K token = ~182K token 语料（实测 726K 字符）
2. 题量充足：1986 题（V1）/ 1922 题（V2）覆盖 5 类能力
3. V2 修正版已下载，可直接使用；V2 的换名（Caroline→Sarah 等）是**有意去污染**——防被测系统的 LLM 从预训练权重背出 V1 答案，用 V2 才能证明答案来自图检索（见 design D1）
4. Mem0 92.5%、Zep 94.7%，有横向基线（口径见 spec 基线表）

LongMemEval 已独立为 `longmemeval-bench` change，覆盖 knowledge-update + abstention 等 LoCoMo 没有的能力。

## What Changes

- 新增 `bench/locomo/` 评测框架：LoCoMo 端到端对话记忆评测
- 新增数据拉取脚本：优先探测复用本机既有 clone（当前在 `bench/longmemeval/data/` 下），否则从 GitHub 克隆
- 新增数据合成加载器 `LoCoMoDataLoader`（**三源合成**）：V2 base conversation + QA 为主体；从 V2 caption 变体（默认 `locomo_v2_moondream.json`，VLM caption 含 OCR）按 `dia_id` 移植 caption（834/910 带图轮，缺失 76 轮为死链）；按**换名映射**（`speaker_a/b` 字段机械建立）把 V1 `evidence` 移植到 V2 题（实测 98%，1881/1922 题精确匹配，仅作诊断指标）
- 新增对话式 ingest 适配器：每会话 = 一次 `mcs.ingest(IngestInput(content=拼接文本, timestamp=会话时间ISO, work_id=sample_id))`——`work_id` 触发 ③b 作品叙事事件抽取（双轨事件）
- 新增图隔离策略：每对话一个独立 SQLite db（隔离靠 db；`work_id` 的作用是启用 ③b，每对话自成 universe）
- 新增评测双轨（**同一套图服务两轨**，语料与问题统一用 V2 人名）：
  - **检索轨**（移植 evidence 的 1881 题）：`mcs.query()` → session 级 Recall@k
  - **QA 轨**（V2 全部 1922 题）：agent.chat(question) → LLM 生成答案 → LLM judge 判对错
- 新增按问题类型的分项指标（5 类，主指标 LLM-judge 正确率）
- 框架 ingest 建图 + agent 查询评测（不修改 `bench/agent_build.py` 共享模块）

## Capabilities

### New Capabilities
- `locomo-eval`: LoCoMo 对话记忆评测框架——数据合成（V2 主体 + V1 移植）、双轨事件 ingest（work_id 启用 ③b）、图隔离、检索+QA 双轨评测、按类型分项指标

### Modified Capabilities
（无——本 change 不修改任何现有模块代码）

### 依赖（独立框架 change，先行落地）
- `work-event-anchor-resolution`：`extract_work_events` prompt 放宽一条规则——**文本内含显式时间锚点时，相对时间 MAY 解析为 ISO 绝对时间**（无锚点仍保留原文形态、不猜测；"建安五年"类作品纪年行为不变）。没有它，"yesterday" 会被原样抽成不可排序的 `narr_timestamp`（排序仅认 ISO / 数字年），temporal 类 71% 的题系统性失分。属框架层改动，按分层原则单列，本 change 声明依赖。

## Impact

- 新增 `bench/locomo/` 目录（不影响现有核心代码）
- 数据落 `bench/locomo/data/`（不入 git）；本机既有 clone 在 `bench/longmemeval/data/locomo_repo|locomo_v2`，脚本探测复用
- 复用现有能力：③b 作品叙事事件抽取、universe 时间轴、timeline 工具、互斥边、source_tracking
- **adversarial 类题**测试"有相关内容但归属错误 → 识别归因错误 → 弃答"——与黄金笼"无相关文档 → 弃答"口径互补
- **temporal 类题**依赖 ③b 叙事事件 + 锚点解析（配套 change）；配套未落地前跑评测，temporal 类将如实反映缺口（71% 题受影响）
- LoCoMo 许可 CC BY-NC 4.0（学术评测合规）
- 全量成本 ~50M token 量级，先单对话（conv-26）试点全链路再放量
