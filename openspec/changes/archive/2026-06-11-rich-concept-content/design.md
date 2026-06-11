## Context

MCS 当前 `extract_concepts` prompt 让 LLM 为每个概念生成简短的 `content`（平均 79 字）。这些简短描述导致：① 每个概念节点 token 占用低 → root 扇出高达 762 → `navigate_hub` 定位困难；② 关系信息以 `statements` 形式存入 extensions 但不被 ContextRenderer 渲染 → 查询时丢失。

当前 statements 链路：`extract_concepts` 的 `relation_hints` → `judge_relations` 生成 `initial_statements` → `write_pipeline` 写入 `node.extensions["statements"]["items"]` → 仅 `LexicalScorer` 读取。ContextRenderer 不渲染 statements，查询管线完全看不到。

### 约束
- 已有图数据 `bench/multihop_rag/outputs/v4flash_full_v2/` 不可动
- `mcs/core/context_renderer.py` 不需修改（已只渲染 content）
- `mcs/stores/` 不需修改（statements 只是 extensions JSON 里的字段）

## Goals / Non-Goals

**Goals:**
- 概念 content 包含足够丰富的信息（2-4 句，含关键事实和关系），使 navigate_hub / select_nodes 能准确判断相关性
- 移除 statements 机制，消除"写入但查询不可见"的死路径
- merge 时将 concept content 追加到目标节点 content（替代写入 statements）
- 自然压缩 root 扇出（更丰富 content → 更多 token → 更早裂变 → 更少直挂 root 的子节点）

**Non-Goals:**
- 不改变边模型（仍然是有向边 + 两条对向语义边）
- 不改变裂变/decide_hub 逻辑
- 不改变查询管线结构
- 不做 embedding 双路召回（独立优化方向）

## Decisions

### D1: extract_concepts prompt 重写

**现状**：`SYSTEM_PROMPT` = "你是知识图谱构建助手。从输入文本中识别独立的概念，如果某概念已存在于「已知相关概念」中，请复用其名称。概念之间的关系用自然语言短语写在 relation_hints 里，不要做谓词归一。"

**新 prompt**：让 LLM 为每个概念生成自包含的 2-4 句描述，覆盖：
- 这个概念是什么（定义）
- 关键事实和数据
- 与其他实体/概念的关系
- 来源文档的上下文

`relation_hints` 保留（用于 judge_relations 建边），但不再转化为 statements。

### D2: judge_relations prompt 简化

移除 `initial_statements`、`statement`、`aliases_to_add` 字段。只保留：
- `action`: merge / create / no_op
- `concept_name`
- `target_id`
- `edges_to`
- `edges_to_names`
- `reason`

parse 函数保持宽容解析（LLM 偶尔输出旧字段也不报错），但不使用 statement 相关字段。

### D3: write_pipeline merge 追加 content

`_dispatch_merge` 中：
- 移除 `initial_statements` → `extensions["statements"]["items"]` 的写入
- 新增：若 `decision.concept.content` 非空且不是目标节点 content 的子串，追加到目标节点 content（用换行分隔）
- 去重：如果追加后 content 重复，跳过

`_dispatch_create` 中：
- 移除 `initial_statements` → `extensions["statements"]["items"]` 的写入

`_dispatch_attach` 中：
- 整体变为 no-op（保留方法签名，打 deprecation warning 日志）

### D4: LexicalScorer 移除 statements 读取

从 `node.content + extensions.statements.items` 双源改为仅 `node.content`。content 已包含所有关系信息，无需额外来源。

## Risks / Trade-offs

1. **extract_concepts 输出 token 增加**：更丰富的 content 意味着每次 LLM 调用输出更多 token。如果 `max_tokens` 太低可能截断 → parse 失败率上升。**缓解**：监控 `LLMParseError` 率；必要时调大 `max_tokens`。
2. **merge 追加 content 可能膨胀**：多次 merge 同一节点时 content 持续增长。**缓解**：追加前检查子串去重；content 过长会触发不变量守门 → 自然裂变。
3. **向后兼容**：旧图的 statements 仍在 extensions 里，LexicalScorer 不再读取它们。对旧图 rerank 有轻微降级，但旧图不重跑所以无实际影响。
