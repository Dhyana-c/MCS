## Context

`graph-model-design.md` §5.1 已写定统一 ingest 流程，但代码只实现了概念 / 事实路径，事件 / source 经游离的 `ingest_event` / `ingest_source` 方法过渡、从不被主 `ingest` 调用（见 [write_pipeline.py](../../../mcs/core/write_pipeline.py)）。本设计把代码接到 §5.1，并落实两个澄清决策：① 事件 / source 由**规则**生成、不经 LLM（保持铁律）；② **每次 ingest 把整个输入记为一个事件**（记录行为，落用户时间轴）。

约束：
- `unified-graph-schema` 既有契约不破：事件 / source 不经 LLM；content 内"转述的过去事件"仍抽成**带时间属性的事实**，不盖成时间轴事件；核心节点 `get_relations` 过滤事件边（载重规则，store 层已落实）。
- 向后兼容：海量调用方仍传 `str`（MCP / agent / bench / examples）。

## Goals / Non-Goals

**Goals:**
- `ingest` 一次调用即走完 §5.1：规则建事件 + source → LLM 抽 content 概念 / 事实 → 事件 / source 背书连边。
- 出处 / 时间轴可回溯（"何时、从哪份资料学到此概念"）。
- 向后兼容 `str` 入参，调用方零改动。
- 载重规则、"事件 / source 不经 LLM"铁律不被破坏。

**Non-Goals:**
- 不引入 LLM 参与事件 / source 的识别 / 切分（铁律不动）。
- 不实现智能 source 自动分类 / 复杂分块（规则切分保持简单，深度切分留作可插拔规则的后续）。
- 不改 MCP / agent 对外接口形态（仍可只传文本；结构化入参的对外暴露留后续）。
- 不改查询侧。

## Decisions

### D1: 结构化输入 `IngestInput`

新增数据类（置于 `mcs/entities/`，与 `EventData` / `SourceData` 同域）：

```python
@dataclass
class IngestInput:
    content: str                       # 走 LLM 抽概念/事实的正文
    timestamp: str | None = None       # 记录时间（ISO 8601）；None → 入库时取 now
    source: SourceData | None = None   # 可选：本次输入的原始资料（规则切分为 source 节点）
    event_name: str | None = None      # 事件节点 name；None → 由 content 规则派生（截断）
    metadata: dict = field(default_factory=dict)
```

复用既有 `SourceData`（`source_type` / `chunks` / `target_ids`）承载 source，不另造类型。

**备选**：把字段直接铺在 `ingest(**kwargs)` 上——否，结构体更清晰、可演进、便于测试。

### D2: `ingest` 重载兼容 `str`

`MCS.ingest` / `WritePipeline.ingest` 接受 `str | IngestInput`。入口处归一化：

```python
if isinstance(data, str):
    data = IngestInput(content=data)   # now 时间戳、无 source
```

`str` 路径产出"一个事件（now）+ 概念 / 事实，无 source"。老调用逐字不变。

**备选**：另开 `ingest_structured()`——否，双入口割裂、调用方要二选一；重载单入口零迁移成本。

### D3: 规则入库作为新首段（流程对齐 §5.1）

管线由 7 段扩为：

```
① 规则入库（不经 LLM）：建事件节点（整输入，带 timestamp）+ source 节点（按 SourceData 切分）
② 前置插件链（原 ①）
③ 关联节点定位（原 ②）
④ 概念提取（LLM，仅 content）
⑤ 关系判定（LLM）
⑥ 图更新 + 背书连边（事件/source → 本次新建概念/事实）
⑦ 压缩判定（守门）
⑧ 自动落盘
```

事件 / source 节点在 ① 先建，使其 id 可用于 ⑥ 的背书连边；即便 content 抽取为空，事件 / source 仍入库（**记录行为已发生**）。

### D4: 背书连边在图更新之后（⑥）

事件 / source 的背书目标 = **本次 ingest 新建 / 命中的概念 / 事实**，其 id 直到 ⑥ `_apply_decisions` 返回才确定。故：

- ① 只**创建**事件 / source 节点（不连背书边）；
- ⑥ 拿到 `changed` 概念 / 事实后，对每个连 `事件 → 概念/事实`、`source → 概念/事实` 的 `关联` 边。

为此把现有 `ingest_event` / `ingest_source` 拆为**「建节点」+「连背书边」两个原语**：对外行为（含 MCP `ingest_event` 工具：建节点 + 按入参 `target_ids` 连边）保持逐字不变，统一 ingest 内部走"先建节点、后按 `changed` 连边"。

### D5: 每次 ingest = 一条记录事件，与"转述过去→事实"区分

ingest 产生的事件代表**记录这一行为**（"我在 timestamp 记下了这段输入"），落用户时间轴。content 内被转述的过去事件（"三年前发生 X"）仍由 LLM 抽成**带时间属性的事实**——二者层级不同，不冲突，`unified-graph-schema` 既有 scenario 不破。

### D6: 幂等与事件创建

`idempotency_check`（WRITE_PREPROCESS）跳过的是**概念 / 事实抽取**；事件创建是 ingest 调用的产物。既有契约「幂等由调用方负责」（调用方 `is_ingested()` 后才决定是否 `ingest()`）不变——真重复时调用方**不调** `ingest`，自然不产生事件。被调用即视为一次有效记录行为、建一个事件。重试导致的事件膨胀由"调用方幂等 + 载重规则（事件不进活跃视图）"双重兜底。

### D7: ⑤ 同名去重仅纳入核心节点（实现期发现）

⓪ 先建的事件节点名由 `content` 派生，会在 ⑤ `_apply_decisions` 的「精确同名去重索引」（`_norm_name` 小写去空白）中出现。若不处理，`content≈概念名`（如 content `"Python"` / 概念 `"Python"`，或 `"c"` / `"C"`）会把**概念错并入同名事件节点**——概念 content 追加到事件、`edges_to` 挂到事件，概念节点丢失。修复：该去重索引**仅纳入核心节点**（`node_class ∈ {概念, 事实}`）；事件 / source 不是概念、不参与去重。这是 ⓪ 把事件放进 store 后才暴露的交互，属本 change 必修的核心正确性（回归测试 `test_concept_not_absorbed_by_same_name_event`）。

### D8: 撤销公开 `ingest_event` / `ingest_source` 入口（归档后修订）

**背景**：D4 当初保留 `ingest_event` / `ingest_source` 为"对外低层入口（向后兼容 MCP 工具）"。归档后复查发现该理由不成立：

- `WritePipeline/MCS.ingest_source`、`MemoryStore.learn_event` **零调用方**；
- `ingest_event` 唯一消费者是 MCP `ingest_event` 工具，而它与 `ingest` 重复（统一 ingest 已自动建时间轴事件），`target_ids` 通常为空 → 建孤儿事件；
- 这两个公开方法**不走 ⑦ 落盘**，单独调用的数据会丢（旧有缺口，非本 change 引入）；
- MCP `ingest_event` 工具违反 `mcp-server` spec「含且仅含 query 与 ingest」。

**决策（推翻 D4 的"保留"）**：删除公开 `MCS.ingest_event` / `ingest_source`、`WritePipeline.ingest_event` / `ingest_source`、`MemoryStore.learn_event`、MCP `ingest_event` 工具。**保留**内部原语 `_build_event_node` / `_build_source_nodes` / `_connect_endorsement_edges`（统一 ingest 在用、不动）。事件 / source 自此**只能经统一 `ingest` 产生**——走 ⑦ 落盘，旧落盘缺口随之消失。删除两份针对公开方法的测试（行为已被 `test_unified_ingest.py` 经私有原语覆盖）。

**影响**：MCP 工具集回到 `{query, ingest}`（与 live spec 一致，无需改 spec）；记事件改为 `ingest` 内容即可。落实"事件 / source 不应有独立公开入口"的初衷。

## Risks / Trade-offs

- **BREAKING `ingest` 签名** → `str` 重载垫片吸收，老调用零改动；仅"想用 source / 自定 timestamp"者改传 `IngestInput`。
- **热概念背书事件累积** → 载重规则（核心 `get_relations` 过滤事件边）已落实，`get_related_events` 时间倒排截断；活跃视图不受影响。须在测试中**显式验证过滤不被新连边破坏**。
- **拆分 `ingest_event` / `ingest_source` 原语** → 可能影响 MCP `ingest_event` 工具行为 → 以「建节点 + 按 target_ids 连边」组合保持对外逐字等价，加回归测试。
- **空 content 仍建事件 / source** → 与"概念为空静默返回"路径交互：须保证早返回前事件 / source 已建并落盘。

## Migration Plan

1. **宪法先行**：`CLAUDE.md` 总体流程 + graph-model-design §5.1 补"每次 ingest 整个输入记为一个事件"，去 §5.1 过渡注。
2. 加 `IngestInput` 数据类。
3. 重构 `WritePipeline`：新规则入库段（建事件 / source）+ ⑥ 背书连边 + `str` 归一化；拆 `ingest_event` / `ingest_source` 为建节点 / 连边两原语。
4. `WriteContext` 增事件 / source 字段。
5. 更新调用方（`mcs_mcp` / `mcs_agent` / `bench` / `examples`）与文档（去 docs-migration 留的过渡注）。
6. 测试（见提案"测试边界"）。

回滚：本 change 局部于写入侧；`str` 路径行为不变，回退影响面小。

## Open Questions

- `IngestInput.source` 单个 `SourceData` 是否够用，还是需 list（一次输入多来源）？倾向：先单个，多来源留后续。
- 事件节点 `name` 的规则派生口径（content 截断长度 / 是否要求调用方给 `event_name`）？倾向：缺省截断派生，允许 `event_name` 覆盖。
