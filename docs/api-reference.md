# API 参考

> MCS 公开面速查：`MCS` 类方法、核心数据类、Builder / 工厂、MCP 工具。签名以 `mcs/` 当前代码为准。
> 概念背景见 [architecture.md](architecture.md)，上手见 [getting-started.md](getting-started.md)。

## `MCS` 类（`mcs/core/mcs.py`）

瘦门面：构造后即可用，所有组装由 Builder 完成。

| 方法 | 签名 | 说明 |
|------|------|------|
| `ingest` | `ingest(data: str \| IngestInput, **metadata) -> WriteContext` | **事件 / source / 概念 / 事实的唯一入口**。走写入管线：⓪ 规则入库（每次把整个输入记为一个事件节点、落时间轴；可选 source 切分，不经 LLM）→ 抽 `content` 概念 / 事实、对齐、判关系与互斥 → 事件 / source 对抽出节点连背书边 → 守门、落盘。`str` 归一化为 `IngestInput(content=text)`（now、无 source），老调用零改动 |
| `query` | `query(text: str, existing_context: list \| None = None) -> Subgraph` | 走查询管线，返回 `Subgraph`；传 `existing_context` 可跳过种子定位、直接对给定节点扩展 |
| `run_maintenance` | `run_maintenance(force: bool = False) -> list[str]` | 跑 `MAINTENANCE` 插件（去重 / 压缩 / 摘要）；`force=True` 忽略 `should_run()`。返回已执行插件名 |
| `register_plugin` | `register_plugin(plugin, target: "writer" \| "reader")` | 向单侧管线注册插件 |
| `register_shared_plugin` | `register_shared_plugin(plugin)` | 同一实例注册到两侧（LLM / 节点扩展等） |
| `unregister_plugin` | `unregister_plugin(name, target) -> bool` | 注销，成功返回 True |
| `get_plugin` | `get_plugin(name) -> Plugin \| None` | 按名查找（优先 write_manager） |
| `show` | `show() -> str` | Markdown 流程图展示双管线插件注册 |
| `shutdown` | `shutdown()` | 关闭所有插件与存储（共享插件只一次） |

> **`get_related_events` 不在 `MCS` 门面上。** 定向查事件（绕过载重规则、时间倒排）经查询引擎调用：
> `mcs.query_engine.get_related_events(node_id, limit=None) -> list[Node]`（同一方法也在 `store` 上）。
> 核心节点的 `get_relations` 不含事件边，需要出处 / 证据时用这个独立检索步。

## 核心数据类（`mcs/entities/`）

### `graph.py`

```python
@dataclass
class Node:
    id: str
    name: str
    content: str
    node_class: str = "概念"          # 概念 / 事实 / 事件 / source
    extensions: dict = {}
    # property hub: bool —— 读写 extensions["hub"]（组织中心标记，无算法含义）

@dataclass
class Edge:
    source_id: str
    target_id: str
    id: str = <uuid4>
    type: str = "关联"                # 关联 / 互斥
    priority: float = 0.0            # 派生值（Phase 2 由 PriorityScorer 算）
    extensions: dict = {}

@dataclass
class Subgraph:
    focus_id: str
    nodes: list[Node] = []
    edges: list[Edge] = []
```

登记常量：`CLASS_CONCEPT/FACT/EVENT/SOURCE`、`NODE_CLASSES`、`CORE_NODE_CLASSES`、`EDGE_ASSOC`/`EDGE_MUTEX`、
`ALLOWED_EDGE_TYPES`、`SEED_ROOT_ID`/`SEED_ROOT_NAME`。`validate_node_class(node_class)` 做登记制校验。

### `decisions.py`（写入管线 + 规则入库）

```python
@dataclass
class ConceptDraft:                  # 阶段③ 抽取输出
    name: str; content: str
    relation_hints: list[str] = []
    node_class: str = "概念"          # 概念 / 事实

@dataclass
class Decision:                      # 阶段④ 输出 / ⑤ 输入
    action: "merge" | "create" | "no_op"
    concept: ConceptDraft | None = None
    target_id: str | None = None
    edges_to: list[dict] = []        # 到已存在节点：[{"target_id": str}]
    edges_to_names: list[dict] = []  # 到同批新概念：[{"target_name": str}]
    aliases_to_add: list[str] = []
    reason: str | None = None
    node_class: str = "概念"
    mutex_with: list[str] = []       # 与已有事实互斥（id）
    mutex_with_names: list[str] = [] # 与同批新事实互斥（名）

@dataclass
class EventData:                     # 规则入库事件结构（ingest ⓪ 段内部建事件节点用）
    name: str; content: str
    timestamp: str | None = None     # ISO 8601
    target_ids: list[str] = []       # 背书目标
    extensions: dict = {}

@dataclass
class SourceData:                    # IngestInput.source 的原始资料结构（规则切分为 source 节点）
    name: str
    source_type: str = ""            # 文件 / 网页 / 段落 / 对话记录
    chunks: list[dict] = []
    target_ids: list[str] = []
    extensions: dict = {}

@dataclass
class IngestInput:                   # 统一 ingest 的结构化输入（str 入参也归一化为此）
    content: str                     # 唯一进 LLM 抽取的字段（也是事件节点记录的正文）
    timestamp: str | None = None     # 记录时间；None → 入库取 now
    source: SourceData | None = None # 可选，按规则切分为 source 节点（不经 LLM）
    event_name: str | None = None    # 事件节点 name；None → content 截断派生
    metadata: dict = {}              # 自由元数据，并入 WriteContext.metadata
```

聚类相关：`Community`（theme / member_ids / strategy / key_concept_id / summary）、`MultiHubDecision`
（communities / unassigned_ids / reason）—— `decide_hub` 的输出结构。

### `config.py` — `MCSConfig`

```python
@dataclass
class MCSConfig:
    mode: str = "knowledge_graph"
    token_budget: int = 8000          # 不变量阈值 T
    max_rounds: int = 5               # 查询 BFS 最大轮数
    max_accumulated_nodes: int = 1000
    auto_persist: bool = True
    shared_plugins: list[str] = []    # 注册到两侧
    write_plugins: list[str] = []
    read_plugins: list[str] = []
    write_llm: str = ""               # 写入 LLM 插件名
    read_llm: str = ""                # 读取 LLM 插件名
    plugin_configs: dict = {}
    prompt_overrides: dict = {}
```

工厂类方法：

- `MCSConfig.knowledge_graph(write_llm="deepseek", read_llm=None)` — Phase 1 默认配置（T=8000、5 轮）。
  `write_llm` / `read_llm` 取短名 `deepseek` / `claude` / `ollama`。
- `MCSConfig.memory_system()` — Phase 2 占位配置。
- `MCSConfig.from_file(path)` — 从 YAML 加载（preset 铺底 + 字段叠加 + `${VAR}` 插值），见 [configuration.md](configuration.md)。

## Builder 与工厂（`mcs/presets/`）

```python
from mcs.presets import Phase1Builder, create_mcs

# Builder：完整控制
mcs = Phase1Builder(config).build()

# 工厂：一行起
mcs = create_mcs(
    write_llm="deepseek", read_llm=None, llm=None,   # llm 指定则读写共用
    db_path="mcs.db",
    token_budget=8000, max_rounds=5, max_accumulated_nodes=1000,
    plugin_configs=None,
)
```

`get_phase1_plugin_registry() -> dict[str, type[Plugin]]` 返回内置插件名→类映射（见 [plugin-system.md](plugin-system.md)）。

## MCP 工具

经 `mcs-mcp` 暴露：`query`、`ingest`（仅这两个）。入参 / 返回见 [mcp-server.md](mcp-server.md)。

## 进一步阅读

- [getting-started.md](getting-started.md) — 端到端示例
- [plugin-system.md](plugin-system.md) — 插件接口与注册
- [architecture.md](architecture.md) — 这些 API 背后的设计
