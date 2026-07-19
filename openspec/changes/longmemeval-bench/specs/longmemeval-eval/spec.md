# longmemeval-eval spec

> 数据格式细节、字段说明、伪代码见本 change 根目录 [`data-format.md`](../../data-format.md)；决策依据见 `design.md`。

## ADDED Requirements

### Requirement: 数据加载与类型拆分

`LongMemEvalDataLoader` SHALL 加载 oracle / S 版 JSON，解析 `haystack_dates`（格式 `"2023/04/10 (Mon) 17:50"`，去星期段后 `"%Y/%m/%d %H:%M"`）并按日期升序排列会话；SHALL 支持按 `question_type` 过滤与 abstention 子集识别（`question_id` 以 `_abs` 结尾）。

#### Scenario: 类型分布钉死

- **WHEN** 加载 oracle 版并按 `question_type` 统计
- **THEN** 分布 MUST 为 {temporal-reasoning: 133, multi-session: 133, knowledge-update: 78, single-session-user: 70, single-session-assistant: 56, single-session-preference: 30}，总 500；`_abs` 题 MUST 为 30（实测分布于 multi-session 12 / temporal-reasoning 6 / knowledge-update 6 / single-session-user 6）；不符即数据版本漂移，MUST 报错而非静默继续

#### Scenario: 时间戳解析

- **WHEN** 解析 `"2023/04/10 (Mon) 17:50"`
- **THEN** 结果 MUST 为 `datetime(2023, 4, 10, 17, 50)`，`.isoformat()` 后为 `"2023-04-10T17:50:00"`

### Requirement: 对话式 ingest——每会话一次，带 session 级溯源

builder SHALL 对每题的每个 haystack 会话执行一次 `mcs.ingest(IngestInput(content=拼接文本, timestamp=会话时间ISO, metadata={"doc_id": question_id, "chunk_id": haystack_session_id}))`，会话按时间升序依次 ingest。拼接格式为逐行 `[会话时间] {role}: {content}`（role ∈ user/assistant，保留角色标注）。

#### Scenario: 摄入行为事件时间戳 = 会话时间

- **WHEN** ingest 某会话（`haystack_dates` 对应值 `"2023/04/10 (Mon) 17:50"`）
- **THEN** 本次摄入行为事件节点 `event_meta.timestamp` MUST 为 `"2023-04-10T17:50:00"`（非实际 ingest 时刻）

#### Scenario: source_tracking 记录会话来源

- **WHEN** 某会话（`haystack_session_id = "answer_4be1b6b4_2"`）ingest 产出概念/事实节点
- **THEN** 这些节点的 `source_tracking.sources` MUST 含 `chunk_id == "answer_4be1b6b4_2"` 的记录

### Requirement: 图隔离——每题独立 db

评测框架 SHALL 为每题（`question_id`）创建独立 SQLite db（`longmemeval_{question_id}.db`）；跨题 MUST NOT 共享任何图数据。

#### Scenario: 跨题零泄漏

- **WHEN** 先后对两道题建图
- **THEN** 两者 MUST 位于不同 db 文件，任一图中 MUST NOT 出现另一题历史的节点

### Requirement: 检索轨 session 级 Recall@k

检索轨 SHALL 以 `mcs.query(question)` 返回节点按 rank 序经 `source_tracking.sources` 的 `chunk_id` 映射为召回会话序列（去重保序），与该题 `answer_session_ids` 比对。主指标 any-evidence hit（gold 与 top-k 交非空），副指标 all-evidence hit；k = 5, 10, 20。

#### Scenario: 命中判定

- **WHEN** 某题 `answer_session_ids == ["S2", "S3"]`，k=5 召回会话序列前 5 为 `["S7", "S2", "S1", "S9", "S4"]`
- **THEN** any-evidence hit MUST 为真，all-evidence hit MUST 为假

### Requirement: QA 轨主指标为 LLM-judge，判定按类型定制

QA 轨 SHALL 对全部 500 题运行 `agent.chat(question)`，答案由 LLM judge 判定（主指标，对齐 LongMemEval 官方 judge 口径与 Zep 报告）；F1 与时间偏移容忍 SHALL 作为副指标单列，MUST NOT 与 judge 数字混入同一对比表。judge 判定规则：knowledge-update 题只认**最新值**（答旧值 = 错误）；multi-session 的 32 个 int 计数题判数值相等；single-session-preference 按 rubric 评分；abstention 题（`_abs`）判弃答语义（正确 = 表达"用户历史中未提及此信息"，答出具体内容 = 错误），MUST NOT 用关键词匹配。

#### Scenario: knowledge-update 只认最新值

- **WHEN** 用户历史中先说"开 Toyota Camry"、后说"换成了 Tesla Model 3"，题问"用户现在开什么车"，agent 答 "Toyota Camry"
- **THEN** judge MUST 判错（旧值）；答 "Tesla Model 3" MUST 判对

#### Scenario: abstention 弃答判定

- **WHEN** `_abs` 题 agent 回答 "The user never mentioned anything about their pet's name"
- **THEN** judge MUST 判为正确（弃答语义成立，即使不含 "I don't know" 字样）

#### Scenario: 口径分离

- **WHEN** 生成 REPORT.md 基线对比表
- **THEN** 主表 MUST 仅含 LLM-judge 口径数字且逐行注明来源口径；F1 / 时间容忍 MUST 单列副表

### Requirement: Oracle 首期与成本护栏

评测 SHALL 以 Oracle 版为首期（S 版 Phase 2、M 版不跑）；脚本 SHALL 支持题数限制参数与断点续跑（建图按 db 文件、评测按已完成 `question_id` 跳过），REPORT MUST 注明所用版本（Oracle 无填充会话、检索难度低于 S，结果不可与 S 版口径混比）。

#### Scenario: 评测 resume

- **WHEN** 评测中断后重跑
- **THEN** 已有结果的 `question_id` MUST 被跳过，仅评测剩余题目
