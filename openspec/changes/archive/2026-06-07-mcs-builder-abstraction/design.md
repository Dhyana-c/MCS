## Context

### 当前状态

MCS 类位于 `mcs/__init__.py`，包含：
1. `_default_plugin_registry()` 函数，硬编码导入 15+ 个具体插件类
2. `MCS.__init__()` 和 `initialize()` 方法，组装整个系统
3. 公共 API 方法 `ingest()`、`query()`、`persist_full()`
4. 单一 `PluginManager`，写入和读取共享同一套插件

这导致：
- `mcs/__init__.py` 成为"包级模块"，但它依赖具体实现（`plugins/phase1/*`）
- 无法在 `core` 层测试 MCS 类而不引入 plugins
- bench 代码重复实现初始化逻辑（`_make_mcs`）
- **核心问题**：写入和读取无法使用不同的插件配置（Entry、Trim、LLM）

### 约束

1. **core 不依赖实现**：`mcs/core/` 不应导入 `mcs/plugins/`
2. **接口稳定**：MCS 类的公共 API 不变（`ingest`、`query`、`persist_full`）
3. **共享存储**：Graph 和 Storage 插件必须共享，保证数据一致性
4. **节点结构一致**：NodeExtension 插件必须共享，保证节点渲染一致

## Goals / Non-Goals

**Goals:**
1. MCS 类移入 `core`，成为纯数据持有者 + 公共 API
2. 引入 `MCSBuilder` 抽象，只依赖 `MCSConfig`
3. 新建 `presets/` 脚手架，提供 Phase1 默认构建器和快捷工厂
4. **分离插件配置**：shared_plugins + write_plugins + read_plugins
5. **双 PluginManager**：write_manager + read_manager，共享插件注册到两者
6. **分离 LLM**：write_llm + read_llm，支持写入用便宜模型、读取用强模型

**Non-Goals:**
1. 不改变 MCS 类的公共 API（`ingest`、`query`、`persist_full`）
2. 不改变插件接口契约
3. **不考虑向后兼容**：开发阶段，全部改为新配置格式

## Decisions

### D1: MCSConfig 字段拆分

**设计**：
```python
@dataclass
class MCSConfig:
    # 分离配置（替代旧 plugins 字段）
    shared_plugins: list[str] = field(default_factory=list)  # Graph/Storage/NodeExtension
    write_plugins: list[str] = field(default_factory=list)   # Compaction/write Postprocess
    read_plugins: list[str] = field(default_factory=list)    # Entry/Trim/Index/read Postprocess
    
    # LLM 分离
    write_llm: str = ""  # 写入 LLM 名称
    read_llm: str = ""   # 读取 LLM 名称
    
    # 其他字段保持
    token_budget: int = 8000
    max_rounds: int = 5
    max_picked: int = 50
    auto_persist: bool = True
    seed_graph_bounding: bool = True
    plugin_configs: dict = field(default_factory=dict)
    prompt_overrides: dict = field(default_factory=dict)
```

**理由**：
- `shared_plugins`：必须共享的插件（Storage、NodeExtension），保证数据一致性和节点结构一致
- `write_plugins`：写入专用插件（Compaction、write_preprocess Postprocess）
- `read_plugins`：读取专用插件（Entry、Trim、Index、Arbitration、query Postprocess）
- `write_llm`/`read_llm`：支持写入用便宜模型（概念提取）、读取用强模型（语义导航）

### D2: MCS 双 PluginManager 架构

**设计**：
```python
class MCS:
    def __init__(self, config: MCSConfig, plugin_registry: dict[str, type[Plugin]]):
        self.config = config
        self.graph = InMemoryGraphStore()  # 共享
        
        # 双 PluginManager
        self.write_manager = PluginManager()
        self.read_manager = PluginManager()
        
        # 共享插件注册到两个 manager（同一实例）
        for name in config.shared_plugins:
            cls = plugin_registry.get(name)
            if cls:
                plugin = cls(config.plugin_configs.get(name, {}))
                self.write_manager.register(plugin)
                self.read_manager.register(plugin)  # 同实例
        
        # 写入专用（只注册到 write_manager）
        for name in config.write_plugins:
            cls = plugin_registry.get(name)
            if cls:
                plugin = cls(config.plugin_configs.get(name, {}))
                self.write_manager.register(plugin)
        
        # 读取专用（只注册到 read_manager）
        for name in config.read_plugins:
            cls = plugin_registry.get(name)
            if cls:
                plugin = cls(config.plugin_configs.get(name, {}))
                self.read_manager.register(plugin)
        
        # LLM 分离引用
        self.write_llm = self.write_manager.get_by_name(config.write_llm)
        self.read_llm = self.read_manager.get_by_name(config.read_llm)
```

**理由**：
- 共享插件（Storage）同一实例注册到两个 manager，保证数据一致性
- Entry/Trim/Index 等只注册到 read_manager，写入时不会使用它们
- Compaction 只注册到 write_manager，读取时不会触发它们

### D3: WritePipeline 使用 read_manager 的 QueryEngine

**设计**：
```python
class MCS:
    def initialize(self):
        # QueryEngine 使用 read_manager + read_llm
        self.query_engine = QueryEngine(
            graph=self.graph,
            llm=self.read_llm,
            plugin_manager=self.read_manager,
            token_budget=self.token_budget,
            ...
        )
        
        # WritePipeline 使用 write_manager + write_llm
        # 但内部 query_engine 是读取的！
        self.write_pipeline = WritePipeline(
            graph=self.graph,
            llm=self.write_llm,
            query_engine=self.query_engine,  # ← 用读取的 query_engine
            plugin_manager=self.write_manager,
            token_budget=self.token_budget,
            config=self.config,
        )
```

**理由**：
- WritePipeline 阶段②"关联节点定位"复用 QueryEngine，语义上属于"读取操作"
- 应使用 read_manager 的 Entry/Trim/Index 插件，而非 write_manager 的
- 这样写入可以用轻量 write_llm（概念提取），但定位关联节点仍用重量 Entry

### D4: MCSBuilder 抽象类

**设计**：
```python
class MCSBuilder(ABC):
    """抽象构建器 - 只依赖 MCSConfig"""

    def __init__(self, config: MCSConfig):
        self.config = config

    @abstractmethod
    def get_plugin_class(self, name: str) -> type[Plugin] | None:
        """根据插件名称返回插件类"""
        ...

    def build(self) -> MCS:
        """构建并初始化 MCS 实例"""
        registry = self._collect_registry()
        mcs = MCS(self.config, plugin_registry=registry)
        mcs.initialize()
        return mcs

    def _collect_registry(self) -> dict[str, type[Plugin]]:
        """从 shared + write + read 收集插件注册表"""
        all_names = (
            self.config.shared_plugins +
            self.config.write_plugins +
            self.config.read_plugins
        )
        # LLM 也加入（即使不在 plugins 列表中）
        for llm in [self.config.write_llm, self.config.read_llm]:
            if llm and llm not in all_names:
                all_names.append(llm)
        
        return {
            name: cls
            for name in all_names
            if (cls := self.get_plugin_class(name)) is not None
        }
```

**理由**：
- 抽象方法 `get_plugin_class` 反转依赖，让子类决定如何查找插件类
- `build()` 封装完整的初始化流程，包括 shared/write/read 分离注册

### D5: Phase1 默认插件分配

**设计**：
```python
PHASE1_SHARED_PLUGINS = [
    "sqlite_storage",      # Storage
    "source_tracking",     # NodeExtension + StorageSchemaExt
    "summary",             # NodeExtension
]

PHASE1_WRITE_PLUGINS = [
    "idempotency_check",   # Postprocess (write_preprocess)
    "fanout_reducer",      # Compaction
    "summary_regen",       # Compaction
]

PHASE1_READ_PLUGINS = [
    "alias_index",         # Index
    "alias_entry",         # Entry (priority=100)
    "hub_fallback",        # Entry (priority=0)
    "priority_trim",       # Trim
]

# rerank 是 opt-in，不加入默认列表

def MCSConfig.knowledge_graph(write_llm="deepseek", read_llm="deepseek"):
    return MCSConfig(
        shared_plugins=PHASE1_SHARED_PLUGINS,
        write_plugins=PHASE1_WRITE_PLUGINS,
        read_plugins=PHASE1_READ_PLUGINS,
        write_llm=f"{write_llm}_llm",
        read_llm=f"{read_llm}_llm",
        plugin_configs={
            "sqlite_storage": {"path": "mcs.db"},
            f"{write_llm}_llm": {...},
            f"{read_llm}_llm": {...},
        },
    )
```

**理由**：
- Storage、NodeExtension 放 shared（数据/节点结构一致）
- Index、Entry、Trim 放 read（只有读取需要）
- Compaction、write_preprocess Postprocess 放 write
- LLM 名称根据 write_llm/read_llm 参数动态生成

## Risks / Trade-offs

### Risk 1: 共享插件生命周期

**风险**：共享插件被两个 manager 管理，`initialize()` 和 `shutdown()` 可能被调用两次

**缓解**：
- PluginManager.shutdown_all() 需防止重复调用（用 `_shutdown` 标记）
- 或在 MCS.shutdown() 中只调用一次 shutdown_all（合并两个 manager）

### Risk 2: 导入循环

**风险**：`presets/phase1.py` 导入 `plugins/`，而 `plugins/` 可能反向导入 `mcs/__init__.py`

**缓解**：
- `plugins/` 只依赖 `core/` 和 `interfaces/`，不依赖 `mcs/__init__.py`
- 已验证 `plugins/` 的导入无循环

### Risk 3: 测试全量更新

**风险**：所有测试需改为新配置格式，工作量较大

**缓解**：
- 开发阶段，一次性更新所有测试
- 提供 `create_mcs()` 快捷工厂，简化测试代码

## Migration Plan

### Phase 1: MCSConfig 字段拆分

1. 新增 `shared_plugins`、`write_plugins`、`read_plugins`、`write_llm`、`read_llm` 字段
2. 移除 `plugins` 字段
3. 更新 `knowledge_graph()` 工厂方法

### Phase 2: MCS 类双 Manager 重构

1. 创建 `mcs/core/mcs.py`，从 `__init__.py` 移入 MCS 类
2. 实现双 PluginManager 架构
3. 实现 shared/write/read 分离注册逻辑

### Phase 3: MCSBuilder 抽象类

1. 创建 `mcs/core/builder.py`
2. 定义 `MCSBuilder` ABC
3. 实现 `_collect_registry()` 从 shared/write/read 收集

### Phase 4: Presets 脚手架

1. 创建 `mcs/presets/__init__.py`
2. 创建 `mcs/presets/phase1.py`
3. 实现 `Phase1Builder` 和 `create_mcs()`

### Phase 5: WritePipeline 调整

1. `WritePipeline` 构造函数接收 read_manager 的 `QueryEngine`
2. 自身使用 `write_manager` 和 `write_llm`

### Phase 6: 测试全量更新

1. 所有测试改为新配置格式
2. 验证双 Manager 架构正常工作
3. 验证写入用 read QueryEngine 正常定位关联节点

### Phase 7: 导出更新

1. `mcs/__init__.py` 从 core 导出 MCS/MCSConfig/MCSBuilder
2. 移除内联 `_default_plugin_registry`
3. 运行全量测试确保无回归