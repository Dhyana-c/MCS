# graph-summary

## Why

记忆 agent（`mcs_agent`）对话时对所服务的记忆图**主题一无所知**——它不知道这张图是关于"某用户的学习笔记"还是"某项目的设计决策"。由此牵出两条相连问题：

1. **路由判断无依据**：当前"该不该进图探索"的决策 100% 交给 LLM、仅由 system prompt（`mcs_agent/loop.py:23`）steering，而 prompt 只定义了"查"的路径（5 个工具），"直接答"的路径**零引导**。于是闲聊 / 通用知识 / 算术等非记忆问题的行为未定义、未测试——LLM 可能对着"你好"先 `search` 一通，或把通用知识导向徒劳的图搜索。
2. **无图级背景**：agent 启动时对图的范围、顶层领域一无所知，要么瞎搜，要么靠 `search(mode=direct)` 看一堆顶层节点名字（粒度过细、缺语义）。

本 change 引入**图级摘要**作为 agent 的背景知识：维护一段"这张记忆图大概是关于什么的"短文本（≤ 1000 字），随图持久化、每次 `learn` 后由 LLM 语义归纳刷新，并在 agent 每轮对话注入 system prompt。摘要让路由判断从"LLM 凭空猜"变为"对照图主题判断"——明显不在摘要范围的（纯通用知识）直接答、可能在内的才进图探索。同时配套优化路由 system prompt：补齐缺失的"何时直接答"路径、探索停止策略、过渡态（无会话历史）的诚实约束。

> **范围界定**：摘要存储为**图级 meta**（非节点字段），不进任何节点的活跃双向视图 token 口径，**不触碰 MCS 核心不变量**（铁律一）。摘要生成复用 write pipeline 阶段⑥的 compaction 调度机制与 MCS 核心 LLM。本 change **不**实现会话历史——按既定设计，对话将作为图里的事件节点由后续 change 承载（当前为过渡态，故 prompt 须诚实约束"不假装记得上文"）。

## What Changes

### 1. store-interface 新增图级 meta kv 原语

- `StoreInterface` 新增 `get_graph_meta(key) -> str | None` / `set_graph_meta(key, value) -> None`（通用 key-value，图级元数据；非节点字段）。
- `InMemoryStore` 用 dict 实现；`SQLiteStore` **复用既有通用 `meta(key, value)` 表**（与 provenance 同表、按 key 区分，图摘要 key=`"graph_summary"`），`set_graph_meta` 即时落库、跨实例 `load` 保真（不新增表，最小改动）。

### 2. 新增 graph-summary compaction 插件

- 新插件 `GraphSummaryPlugin`（实现 `CompactionPluginInterface`，`PluginType.COMPACTION`），位于 `mcs/plugins/maintenance/graph_summary.py`。
- write pipeline 阶段⑥调度：`should_run` 判"本次 `changed_nodes` 含 `role="concept"` 新节点" → `run` 读 `__seed_root__` 的层级子（顶层 hub）的 name+content → 经注入的 `llm_caller`（MCS 核心 LLM）**语义归纳**为图主题摘要（≤ `GRAPH_SUMMARY_TOKEN_BUDGET`，默认 1000 字——字符口径，与 `gen_summary` 一致；`GRAPH_SUMMARY_TOKEN_BUDGET` 为预算概念名，实现映射见 design 决策4）→ `set_graph_meta("graph_summary", text)`。
- **归纳必须 LLM 语义**（呼应铁律二），禁止机械拼接 / 空洞聚合标签。归纳异常隔离为日志、不阻塞 ingest（保留旧摘要）。

### 3. MemoryStore 新增 graph_summary 原语

- `MemoryStore.graph_summary() -> str`：worker 线程读 `get_graph_meta("graph_summary")`，返回摘要文本（无则空串）。供 agent 每轮取最新摘要。

### 4. agent 注入摘要 + 路由 prompt 改写

- `MemoryAgent.chat()` 每轮开头取 `memory.graph_summary()`，注入 system prompt 的「当前记忆图主题」段。
- 改写 `DEFAULT_SYSTEM_PROMPT`：补「何时直接回答（不调工具）」「探索策略（避免空转）」「记忆诚实（含过渡态：不假装记得本轮之前的对话）」段；保留全部 5 工具说明与跨工具 id 引用规则。
- 喂前对摘要做 ≤ 预算校验 / 截断（第二道闸，防归纳超标）。

### 5. spec 同步

- 新增 capability `graph-summary`；修改 `store-interface`（图级 meta 原语 + 持久化）、`memory-agent`（路由 prompt 契约 + 摘要注入 + `graph_summary` 原语）。

## Capabilities

### New Capabilities

- `graph-summary`：图级摘要的存储（store 图级 meta）、生成（compaction 插件，learn 后 LLM 归纳顶层 hub ≤ 预算）、读取。

### Modified Capabilities

- `store-interface`：新增图级 meta kv 原语（`get_graph_meta` / `set_graph_meta`）+ 持久化 round-trip。
- `memory-agent`：路由 system prompt 契约（何时直接答 / 何时探索 / 探索停止 / 过渡态诚实）；摘要注入 agent system prompt；`MemoryStore.graph_summary` 原语。

## Impact

### 代码变更

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `mcs/core/store.py` | 修改 | `StoreInterface` 加 `get_graph_meta` / `set_graph_meta` 抽象方法 |
| `mcs/stores/in_memory.py` | 修改 | dict 实现 meta kv |
| `mcs/stores/sqlite_store.py` | 修改 | 复用既有 `meta` 表实现 `get/set_graph_meta`（不新增表） |
| `mcs/plugins/maintenance/graph_summary.py` | 新增 | `GraphSummaryPlugin`（CompactionPluginInterface） |
| `mcs/prompts/` | 修改 | 注册 `gen_graph_summary` PromptBundle（新 purpose） |
| `mcs/presets/phase1.py` | 修改 | 注册表加 `graph_summary` |
| `mcs/entities/config.py` | 修改 | `PHASE1_WRITE_PLUGINS` 默认列表加 `graph_summary`（默认每次 learn 触发） |
| `mcs_agent/memory.py` | 修改 | `MemoryStore.graph_summary()` 原语 |
| `mcs_agent/loop.py` | 修改 | `chat()` 注入摘要 + 改写 `DEFAULT_SYSTEM_PROMPT` |
| `tests/...` | 新增 | store meta、graph_summary 插件、agent 注入与路由测试 |

### 依赖关系

- 依赖 `store-interface`（新增原语）、`plugin-protocol`（`CompactionPluginInterface`，既有）、`write-pipeline`（阶段⑥调度，既有）。
- `memory-agent` 依赖本 change 的 `graph-summary` 与 `store-interface` delta。

### 风险

- **复用既有 `meta` 表**（不新增 schema）：图摘要与 provenance 同表、按 key 区分，须保证互不覆盖、`set_graph_meta` 即时落库 + 跨实例 `load` 保真；按核心代码规范全测试覆盖（规则 10）。
- **每次 learn 多一次 LLM 调用**（归纳摘要）：learn 本为重操作，增量可接受；归纳失败 MUST 隔离、不阻塞 ingest。
- **摘要进 system prompt 的固定开销**（≤ 1000 字，一次性，不随 ReAct 轮次累加）：对 agent 上下文可接受；须喂前截断防超标。
