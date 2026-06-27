# 插件体系

> MCS 的核心引擎稳定不变，功能通过插件链组合。本文讲清 14 类插件、统一基类、注册机制、生命周期，
> 以及如何写一个自定义插件。契约见 [`openspec/specs/plugin-protocol`](../openspec/specs/plugin-protocol/spec.md)。

## 统一基类

所有插件继承 `mcs/core/plugin.py` 的 `Plugin`（ABC）：

| 方法 | 必填 | 作用 |
|------|:--:|------|
| `get_name() -> str` | ✓ | 插件标识符；用于日志、配置索引、`node.extensions` 键名 |
| `get_type() -> PluginType` | ✓ | 主类型；`PluginManager` 按它索引 |
| `get_types() -> set[PluginType]` | | 多接口插件覆写，返回其全部类型（默认 `{get_type()}`） |
| `get_priority() -> int` | | 链内排序（越大越先）；默认 `0` |
| `execute(**kwargs) -> Any` | ✓ | 统一执行入口，便于管线统一调用 |
| `initialize(context)` / `shutdown()` | | 生命周期钩子，默认空操作 |

每类插件还各有一个**接口 ABC**（`mcs/interfaces/`），在 `Plugin` 之上定义该类型的专属方法。

## 14 类 PluginType

`PluginType` 枚举（`mcs/core/plugin.py`）定义 14 个有效类型 + 2 个废弃别名：

| PluginType | 接口（`mcs/interfaces/`） | 关键方法 | Phase 1 内置 |
|---|---|---|---|
| `ENTRY` | `EntryPluginInterface` | `locate(query, ctx) -> list[Node]`；`exclusive` | AliasEntry, HubFallback |
| `TRIM` | `TrimPluginInterface` | `trim(...)` | PriorityTrim,（SemanticTrim opt-in） |
| `ARBITRATION` | `ArbitrationPluginInterface` | `arbitrate(...)` | —（≤1，单一职责） |
| `WRITE_PREPROCESS` | `WritePreprocessPluginInterface` | `preprocess(text, ctx: WriteContext) -> str` | IdempotencyCheck |
| `QUERY_PREPROCESS` | `QueryPreprocessPluginInterface` | `preprocess(text, ctx: QueryContext) -> str` | — |
| `POSTPROCESS` | `PostprocessPluginInterface` | `process(input, ctx) -> Any` | Rerank（opt-in） |
| `COMPACTION` | `CompactionPluginInterface` | `should_run(changed, store)`；`run(...)` | FanoutReducer, SummaryRegen, GraphSummary |
| `INDEX` | `IndexInterface` | `build/lookup/add_entry/remove_entry/update_entry` | AliasIndex |
| `LLM` | `LLMInterface` | `call(purpose, nodes_in?, free_args?) -> Any` | DeepSeek, Claude, Ollama |
| `NODE_EXTENSION` | `NodeExtensionInterface` | `schema/default/serialize/deserialize/render(node, purpose)` | SourceTracking, Summary |
| `EDGE_EXTENSION` | `EdgeExtensionInterface` | `schema/default/serialize/deserialize/render(edge, purpose)` | —（opt-in） |
| `STORAGE_SCHEMA_EXT` | `StorageSchemaExtensionInterface` | `node_columns()`；`auxiliary_tables()` | SourceTracking（多接口） |
| `MAINTENANCE` | `MaintenanceInterface` | `run(store)`；`should_run()` | FanoutReducer / SummaryRegen / GraphSummary |

废弃别名：`PREPROCESS` → 指向 `WRITE_PREPROCESS`（保留一个版本后移除）。`SEED_SELECTOR` 已移除——语义筛选并入 `TrimPlugin`（`SemanticTrimPlugin`）。

> **多接口插件**：一个插件可同时实现多个类型——如 `SourceTrackingPlugin` 既是 `NODE_EXTENSION` 又是
> `STORAGE_SCHEMA_EXT`，覆写 `get_types()` 返回 `{NODE_EXTENSION, STORAGE_SCHEMA_EXT}`，`PluginManager`
> 按每个类型都索引到它。

## 双 PluginManager 与执行链

`MCS` 持两套 `PluginManager`：`write_manager`（写入侧）与 `read_manager`（读取侧）。`PluginManager`
按 `PluginType` 索引插件；同类型多个插件按 `get_priority()` 排序成链。写 / 读分离让两侧可用不同 LLM 后端
（`write_llm` / `read_llm`），也让 LLM、`NodeExtension` 这类**共享插件**用同一实例注册到两侧。

## 注册机制

插件不在代码里硬编码，而是经 `MCSConfig` 的三个列表声明，由 `MCSBuilder.build()` 按名解析、实例化、注册：

```python
config = MCSConfig(
    shared_plugins=["source_tracking", "summary"],      # 注册到两侧
    write_plugins=["idempotency_check", "fanout_reducer"],
    read_plugins=["alias_index", "alias_entry", "hub_fallback", "priority_trim"],
    write_llm="deepseek_llm", read_llm="deepseek_llm",
    plugin_configs={"deepseek_llm": {"api_key": "..."}},
)
```

`Phase1Builder.get_plugin_class(name)` 的查找顺序：

1. **内置注册表**（`get_phase1_plugin_registry()`）命中 → 返回插件类；
2. 无 `:` 的未知名 → 返回 `None`（被跳过、不抛异常）；
3. 含 `:` 的 `"module:attr"` → import-path 解析；失败或结果非 `Plugin` 子类 **MUST 抛**（用户配置错误，不静默）。

第 3 条让你无需改核心即可挂第三方插件——配置里写 `"my_pkg.exts:MyPlugin"`，对应 `plugin_configs` 的键
也用**整条 import-path 字符串**（运行期注册名是其 `get_name()` 返回值）。详见 [configuration.md](configuration.md)。

## 生命周期

```
build()  →  实例化插件  →  initialize(context)  →  [ ingest / query 反复调用 ]  →  shutdown()
```

- `initialize(context)`：build 时调用，可访问 graph / config 等做一次性准备（如 `IndexInterface.build`）。
- `shutdown()`：`MCS.shutdown()` 时调用，每个插件实例只 shutdown 一次（共享插件不重复）。

## 自定义插件示例

写一个把文本统一转小写的写入前置插件：

```python
from mcs.core.plugin import PluginType
from mcs.interfaces.write_preprocess_plugin import WritePreprocessPluginInterface


class LowercasePlugin(WritePreprocessPluginInterface):
    def get_name(self) -> str:
        return "lowercase"

    # get_type() 由接口基类返回 PluginType.WRITE_PREPROCESS

    def preprocess(self, text: str, ctx) -> str:
        return text.lower()

    def execute(self, **kwargs) -> str:
        return self.preprocess(kwargs["text"], kwargs.get("ctx"))
```

挂载（两种方式）：

```python
# A. 代码注册
mcs.register_plugin(LowercasePlugin(), target="writer")

# B. 配置 import-path（无需改核心）
#   write_plugins: ["my_pkg.plugins:LowercasePlugin"]
```

## 内置插件清单（Phase 1）

来自 `get_phase1_plugin_registry()`：

| 名称 | 类型 | 作用 |
|------|------|------|
| `source_tracking` | NODE_EXTENSION + STORAGE_SCHEMA_EXT | 记录节点来源文档 / chunk，供出处回读与评测映射 |
| `summary` | NODE_EXTENSION | 节点摘要字段 |
| `idempotency_check` | WRITE_PREPROCESS | 跳过已摄入的相同块，避免重复建图 |
| `fanout_reducer` | COMPACTION | 邻域超 T 时经 `decide_hub` 裂变 + 星型重组（守门主力） |
| `summary_regen` | COMPACTION | 重组后再生摘要 |
| `graph_summary` | COMPACTION | 图级主题摘要（learn 后归纳顶层 hub） |
| `alias_index` | INDEX | 名 / 别名倒排索引 |
| `alias_entry` | ENTRY | 字面匹配名 / 别名定位种子（主力，priority=100） |
| `hub_fallback` | ENTRY | 无命中时回退到顶层 hub（priority=0） |
| `priority_trim` | TRIM | 按 priority 截断候选集 |
| `deepseek_llm` / `claude_llm` / `ollama_llm` | LLM | 三种 LLM 后端适配 |
| `semantic_trim` | TRIM | 语义筛选（opt-in，需手动注册） |
| `rerank` | POSTPROCESS | 查询结果词法重排（opt-in） |

> `sqlite_storage` 不是插件，是 Store 配置项（`plugin_configs["sqlite_storage"]["path"]`），不在注册表中。

## 进一步阅读

- [architecture.md](architecture.md) — 插件体系在整体架构中的位置
- [api-reference.md](api-reference.md) — `MCS.register_plugin` 等 API
- [configuration.md](configuration.md) — 用 YAML 声明插件链与 import-path 第三方插件
