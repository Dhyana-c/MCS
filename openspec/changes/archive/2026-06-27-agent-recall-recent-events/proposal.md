## Why

记忆 agent 的 `recall` 是 5 个导航工具中唯一仍是空壳的——`MemoryStore._do_recall` 直接返回「[未实现] recall（热点事件）暂不可用：依赖事件节点与热点排序」。但这一前提已不成立：MCS 框架层（`unified-graph-schema` 已归档落地）早已具备事件节点（写管线规则入库、`event_meta.timestamp`）与定向查 `StoreInterface.get_related_events`（时间倒排）。agent 缺一个「最近发生了什么」的时间线入口，使 LLM 能回应「我最近记了什么 / 最近有什么」这类时间相关问题——这是导航工具集里最后一块未实装的能力。

## What Changes

- **实装 `MemoryStore._do_recall(limit)`**：扫全图 `node_class=事件` 节点 → 按 `event_meta.timestamp` 时间倒排（无 timestamp 者排末尾）→ **全文渲染**、按**条数 `limit` 与 token 上界 T 双约束截断**（纳入后的完整渲染文本超 T 即停；最近 1 条无条件全文返回）→ 含节点 id 的 LLM 可读文本；无事件返回空提示。
- **排序口径 = 纯近期时间线**（不掺热度）：事件节点无专门「热度」字段，掺热度需引入无依据的加权调参；忠实「最近发生」用时间倒排，口径与 `StoreInterface.get_related_events` 对齐。
- **recall 工具语义改名**：schema 描述与 `DEFAULT_SYSTEM_PROMPT` 由「近期热点事件（未实现）」改为「回忆最近发生的事件（时间倒排）」；**工具名 `recall` 保留**（不破坏 handler / dispatch / 测试引用）。
- **不动框架层**：`mcs/core`、`mcs/stores`、`mcs/entities` 一行不改；recall 只读消费 `store.get_all_nodes()` 与 `query_engine.token_budget`（`.T` + `.estimate`）。
- **接入链路已就绪**：`_recall` handler、`BUILTIN_TOOLS["recall"]` schema、loop `_dispatch`、`ToolsetConfig` 默认启用——均无需改动。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `memory-agent`：`recall 原语（热点回忆）` requirement 由「返回未实现提示」改为「返回最近事件（时间倒排、纯近期口径）」；顺带清理 `记忆工具集` requirement 里把 recall 当「未实现」举例的过时措辞。

## Impact

- **代码**：
  - `mcs_agent/memory.py`：实装 `_do_recall`（全文渲染 + T 预算截断，经 `query_engine.token_budget` 只读）+ 渲染 helper（复用 `_render_nodes` 的 name==content 单份 + 带 id 口径、每条加 timestamp）+ 补 `CLASS_EVENT` import + 模块 docstring 去掉 recall 空壳说明。
  - `mcs_agent/tools.py`：`recall` schema 的 `description` 去「未实现」。
  - `mcs_agent/loop.py`：`DEFAULT_SYSTEM_PROMPT` 的 recall 行去「未实现」。
- **测试**：`tests/test_agent_memory.py` 的 `test_recall_unimplemented` 改写为正向用例（空图 / 时间倒排 / `limit` 截断 / 无 timestamp 排末尾 / 同 timestamp 确定性次序 / T 预算截断 / 单条超 T 至少返回最近 1 条），FakeStore 补 `get_all_nodes`、FakeQueryEngine 补 `token_budget`，模块 docstring 去「空壳」。其它测试文件里的 mock `recall`（`test_agent_loop` / `test_agent_trace` / `test_agent_tools`）测的是调度而非实现，不动。
- **文档**：`docs/memory-agent.md` 两处同步——recall 工具表 `✗（依赖事件热点排序）` → `✓（最近事件时间倒排）`、第 41 行「未实现模式空壳」措辞。
- **API / 依赖**：无新增依赖；工具名 `recall` 不变，无 BREAKING。
- **不变量**：recall 只读、经单 worker 线程，不触发写 / 守门 / 裂变，不影响核心图有界性（铁律一不受影响）。
