# locomo-eval Specification

## Purpose
TBD - created by archiving change conversational-memory-bench. Update Purpose after archive.
## Requirements
### Requirement: 数据三源合成

`LoCoMoDataLoader` SHALL 以 **V2 base conversation + QA 为唯一主体**（建图语料与评测问题同用 V2 人名）；SHALL 按 `dia_id` 从 V2 caption 变体（config `caption_variant` ∈ {moondream, qwen, minicpm}，默认 moondream）移植 VLM caption；SHALL 按换名映射（仅由两版 `speaker_a/b` 字段机械建立，词边界替换 + 大小写不敏感精确匹配，**不经 LLM**）把 V1 `evidence` 移植到 V2 题。MUST NOT 用 V1 人名的问题查询 V2 语料建的图（V2 为去污染换名版，人名对不上）；MUST NOT 使用 V1 的 `blip_caption`（无 OCR，弃用）。

#### Scenario: caption 按 dia_id 从 caption 变体移植

- **WHEN** 加载任一对话，V2 base 某轮带 `img_url`，且所选 caption 变体同 `dia_id` 轮有 `{variant}_caption`
- **THEN** 合成后该轮 MUST 带上该 caption；全量移植数 MUST = 834（缺失 76 轮为死链图像，保持无 caption）
- **AND** 移植前 MUST 校验 caption 变体 conversation 与 base 逐轮 text 一致，不一致即报错

#### Scenario: evidence 移植命中率校验

- **WHEN** 全量 10 对话合成完成
- **THEN** V2 1922 题中移植到 `evidence` 的题数 MUST ≥ 95%（实测 1881/1922 = 98%）
- **AND** 未命中的题 `evidence` 为空、仅参与 QA 轨，MUST NOT 参与检索轨

#### Scenario: 类别映射钉死

- **WHEN** 按 `category` 统计合成后的 V2 QA
- **THEN** 分布 MUST 为 {1: 261, 2: 308, 3: 94, 4: 821, 5: 438}（1=multi-hop、2=temporal、3=open-domain、4=single-hop、5=adversarial），总 1922；不符即数据版本漂移，MUST 报错而非静默继续

### Requirement: 对话式 ingest 产生双轨事件

builder SHALL 对每个会话执行一次 `mcs.ingest(IngestInput(content=拼接文本, timestamp=会话时间ISO, work_id=sample_id, metadata={"doc_id": sample_id, "chunk_id": "session_N"}))`，会话按时间升序依次 ingest。拼接格式为逐行 `[会话时间] 说话者: 文本`，带 caption 轮次追加 ` [shared image: {caption}]`。

#### Scenario: 当下事件落 __reality__ 时间轴

- **WHEN** ingest 某会话（会话时间 `"1:56 pm on 8 May, 2023"`）
- **THEN** 本次摄入行为事件节点 MUST `universe="__reality__"` 且 `event_meta.timestamp == "2023-05-08T13:56:00"`（解析格式 `"%I:%M %p on %d %B, %Y"` → `.isoformat()`）

#### Scenario: 谈话中的事件落对话 universe 叙事时间轴

- **WHEN** ingest 的会话文本含叙述发生（如 "I went to a LGBTQ support group yesterday"）
- **THEN** ③b `extract_work_events` MUST 被触发（`work_id` 非空），产出的叙事事件节点 MUST 归 `sample_id` 对应的 canonical universe（非 `__reality__`）
- **AND** temporal 类评测经 `timeline`（对话 universe）读取叙事事件，MUST NOT 依赖摄入行为事件回答"事发时间"

### Requirement: 图隔离——每对话独立 db

评测框架 SHALL 为每个对话（`sample_id`）创建独立 SQLite db（`locomo_{sample_id}.db`）；`work_id` 的作用是启用 ③b 与 universe 归属，MUST NOT 依赖它做跨对话隔离。

#### Scenario: 跨对话零泄漏

- **WHEN** 先后建图 conv-26 与 conv-30
- **THEN** 两者 MUST 位于不同 db 文件，任一图中 MUST NOT 出现另一对话的节点

### Requirement: 检索轨 session 级 Recall@k

检索轨 SHALL 仅对移植到 `evidence` 的题运行：`mcs.query(question)` 返回节点按 rank 序经 `source_tracking.sources` 的 `chunk_id`（`"session_N"`）映射为召回 session 序列（去重保序）；gold = evidence `dia_id` 的 `D{N}` 前缀集合。主指标为 any-evidence hit（gold 与 top-k 交非空），副指标 all-evidence hit；k = 5, 10, 20。

#### Scenario: dia_id 映射 session

- **WHEN** 某题 `evidence == ["D1:3", "D2:8"]`
- **THEN** gold session 集合 MUST 为 `{1, 2}`

#### Scenario: 命中判定

- **WHEN** k=5 且召回 session 序列前 5 为 `[3, 1, 7, 4, 9]`，gold 为 `{1, 2}`
- **THEN** any-evidence hit MUST 为真，all-evidence hit MUST 为假

### Requirement: QA 轨主指标为 LLM-judge

QA 轨 SHALL 对 V2 全部 1922 题运行 `agent.chat(question)`，答案由 LLM judge 判定语义等价（主指标，对齐 Mem0/Zep 口径）；F1 与时间偏移容忍 SHALL 作为副指标单列，MUST NOT 与 LLM-judge 数字混入同一对比表。adversarial 类（category 5）的弃答判定 SHALL 交 LLM judge（正确 = 判定答案表达"该信息未被提及"；答出具体内容尤其 `adversarial_answer` = 错误），MUST NOT 用关键词匹配。

#### Scenario: adversarial 弃答判定

- **WHEN** adversarial 题 agent 回答 "Sarah never discussed that in the conversation"
- **THEN** judge MUST 判为正确（弃答语义成立，即使不含 "not mentioned" 字样）

#### Scenario: 口径分离

- **WHEN** 生成 REPORT.md 基线对比表
- **THEN** 主表 MUST 仅含 LLM-judge 口径数字，且逐行注明来源口径；F1 / 时间容忍 MUST 单列副表

### Requirement: 成本护栏与断点续跑

评测脚本 SHALL 支持 `--max-conversations N` 限制对话数；建图 resume（db 已存在则跳过）与逐题 resume（已评测 question 跳过）SHALL 默认开启；默认试点顺序 conv-26 优先。

#### Scenario: 建图 resume

- **WHEN** `locomo_conv-26.db` 已存在时重跑建图
- **THEN** conv-26 MUST 被跳过、不重复 ingest

