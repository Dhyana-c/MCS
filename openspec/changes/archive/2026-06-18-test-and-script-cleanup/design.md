## Context

### 当前状态

测试代码中存在多处重复的构建/初始化逻辑：

1. **`tests/conftest.py:_MockLLMBuilder.build()`**
   - 创建动态 `_MockBuilder` 子类继承 `MCSBuilder`
   - 但 `build()` 方法完全重写，没有调用 `super().build()`
   - 手动组装 Store → TokenBudget → PluginManager → 插件注册 → 初始化 → 管线构建 → MCS

2. **`tests/test_pipeline_write.py:_build_mcs_with_store()`**
   - 手动组装，支持外部传入 SQLiteStore
   - 与 MCSBuilder.build() 逻辑高度重复

3. **`tests/test_mcs_api.py:_build_mcs()`**（**保留，不纳入去重**）
   - 刻意最小化手动组装：仅注册 `mock_llm`、无 shared/write/read 插件，供 14 个门面 API 测试（register/unregister/show/shutdown）隔离使用
   - 与 `MCSBuilder.build()` 结构相似但语义不同（非重复），强行替换会注入额外插件、改变 `test_show_*` / `test_shutdown_*` 断言

4. **`tests/test_hub_fallback.py:_init()`、`tests/test_directed_navigation.py:_init_plugin()`**
   - 相同的 PluginManager + PluginContext 初始化模式

5. **`tests/test_directed_hierarchy.py` 和 `tests/test_seed_graph.py` 的 `_fanout_with_root()`**
   - 完全相同的代码
6. **`tests/test_anti_regression.py` 的 `_fanout_with_root(graph, token_budget, mock_llm, **extra_cfg)`**
   - 与第 5 点主体相同（签名多 `**extra_cfg`），**但全文件无调用点——属未被调用的死定义**，直接删除即可，不构成参数化需求
7. **`tests/test_pipeline_query.py` 与 `tests/test_dual_edge.py` 的 `_build_engine()`**
   - 同为「PluginManager + 插件注册 + PluginContext 初始化 + QueryEngine 构建」的重复，默认参数略有差异

### 约束

- MCSBuilder 的 `build()` 方法是完整的 14 步流程
- `Phase1Builder` 已证明"动态子类 + 委托 get_plugin_class"模式可行
- 测试不应依赖外部资源（API 密钥、网络）
- 测试构建器需要支持自定义 Store（InMemoryStore / SQLiteStore）

### 利益相关者

- 测试代码维护者
- bench 脚本用户

---

## Goals / Non-Goals

**Goals:**

1. 让 `_MockLLMBuilder` 正确继承 `MCSBuilder.build()`，只覆写 `get_plugin_class()`
2. 提供测试专用的 `MockLLMBuilder` 类，支持 Mock LLM 注入和自定义 Store
3. 提取插件初始化 helper 到 `conftest.py`，消除测试文件间重复
4. 删除过期脚本 `_run_eval_variants.py`

**Non-Goals:**

- 不修改 MCSBuilder 或 Phase1Builder 的核心逻辑

---

## Decisions

### Decision 1: _MockLLMBuilder 正确继承 MCSBuilder

**选择：** 将现有私有 `_MockLLMBuilder` 重构为公开的 `MockLLMBuilder`，其动态子类调用 `super().build()`

**理由：**

- `MCSBuilder.build()` 已封装完整的 14 步流程
- 测试构建器只需覆写 `get_plugin_class()` 返回 MockLLM
- 复用父类逻辑可避免测试代码与主代码不同步

**替代方案：**

1. **不继承，保持现状**：测试代码与主代码分叉，未来维护成本高
2. **提取 Builder 基类**：过度设计，MCSBuilder 已经是抽象基类

**实现方式：**

```python
class MockLLMBuilder:
    def __init__(self, config: MCSConfig, mock_llm: MockLLM, store: StoreInterface | None = None):
        self.config = config
        self._mock_llm = mock_llm
        self._store = store  # 可选的外部 Store
        self._registry: dict[str, type[Plugin]] | None = None

    def get_plugin_class(self, name: str) -> type[Plugin] | None:
        if name == "mock_llm":
            return MockLLM
        if self._registry is None:
            from mcs.presets import get_phase1_plugin_registry
            self._registry = get_phase1_plugin_registry()
        return self._registry.get(name)

    def build(self) -> MCS:
        from mcs.core.builder import MCSBuilder

        class _MockBuilder(MCSBuilder):
            def __init__(self, config, outer):
                super().__init__(config)
                self._outer = outer

            def get_plugin_class(self, name: str) -> type[Plugin] | None:
                return self._outer.get_plugin_class(name)

            def _instantiate_plugin(self, name: str) -> Plugin | None:
                # 特殊处理 mock_llm：直接返回注入的实例
                if name == "mock_llm":
                    return self._outer._mock_llm
                return super()._instantiate_plugin(name)

            def _init_store(self) -> StoreInterface:
                # 支持外部传入的 Store
                if self._outer._store is not None:
                    return self._outer._store
                return super()._init_store()

        builder = _MockBuilder(self.config, self)
        return builder.build()
```

### Decision 2: 提取测试初始化 helper（init_plugin_manager / make_query_engine）

**选择：** 在 `tests/conftest.py` 添加两个 helper：

- `init_plugin_manager()`：封装 `_init()` / `_init_plugin()` 的 PluginManager + PluginContext 初始化，**返回主 plugin 实例**
- `make_query_engine()`：封装 `_build_engine()` 的「PluginManager + 插件注册 + PluginContext 初始化 + QueryEngine 构建」，**返回 QueryEngine**

**理由：**

- `_init()` 和 `_init_plugin()` 的差异仅是 `config=None` vs `config=MCSConfig()`，可由 `init_plugin_manager()` 统一
- `test_pipeline_query._build_engine` 与 `test_dual_edge._build_engine` 同为「PluginManager + 插件注册 + PluginContext 初始化 + QueryEngine 构建」，但二者**返回 QueryEngine**（而非单个插件），与 `init_plugin_manager` 语义不同，故单独提取 `make_query_engine()`
- 两版 `_build_engine` 默认参数略有差异（`max_rounds` / `max_accumulated_nodes` / `token_budget`），统一为 helper 的默认值

**实现方式：**

```python
def init_plugin_manager(
    store: InMemoryStore,
    plugin: Plugin,
    extra_plugins: list[Plugin] | None = None,
    config: MCSConfig | None = None,
) -> Plugin:
    """初始化 PluginManager 并返回主插件实例。"""
    from mcs.core.plugin_manager import PluginContext, PluginManager
    from mcs.core.token_budget import TokenBudget

    pm = PluginManager()
    for p in extra_plugins or []:
        pm.register(p)
    pm.register(plugin)

    ctx = PluginContext(
        store=store,
        config=config or MCSConfig(),
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    return plugin


def make_query_engine(
    store,
    llm,
    *extra_plugins,
    max_rounds: int = 3,
    max_accumulated_nodes: int = 1000,
    token_budget: int = 8000,
) -> "QueryEngine":
    """初始化 PluginManager（注册 llm + extra_plugins）并构建 QueryEngine（测试用）。

    PluginContext 的 config 为 None（QueryEngine 侧无需 config）；不传 relation_model，
    与现有 `_build_engine` 行为一致。
    """
    from mcs.core.plugin_manager import PluginContext, PluginManager
    from mcs.core.query_engine import QueryEngine
    from mcs.core.token_budget import TokenBudget

    pm = PluginManager()
    pm.register(llm)
    for p in extra_plugins:
        pm.register(p)
    ctx = PluginContext(
        store=store,
        config=None,  # type: ignore[arg-type]
        token_budget=TokenBudget(token_budget),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    return QueryEngine(
        store=store,
        llm=llm,  # type: ignore[arg-type]
        plugin_manager=pm,
        token_budget=TokenBudget(token_budget),
        max_rounds=max_rounds,
        max_accumulated_nodes=max_accumulated_nodes,
    )
```

### Decision 3: 删除过期脚本

**选择：** 删除 `_run_eval_variants.py`

**理由：**

- 早期一次性 A/B 实验（rerank + alias 开/关对比），硬编码 `D:\code\mcs\.env` 与本地 `multihop_chat_200_v2.db`，仅本机可跑
- 底层能力（`MultiHopEvalRunner`）仍在 `bench/multihop_rag` 中保留，需要时可重写
- 以 `_` 开头暗示临时/实验性文件

> 注：`_run_eval_variants.py` 已于 `236bd58`（统一 bench 目录）删除，本 change 仅登记该删除契约。

### Decision 4: 提取 bench/_env.py 统一 .env 加载

**选择：** 新建 `bench/_env.load_dotenv(env_file=None) -> bool`，封装 .env 解析；`scripts/_common.setup_env` 与 `runner._maybe_load_dotenv` 改为复用。

**理由：**

- 两处的 .env 解析逻辑逐字相同（`setdefault`、忽略 `#`/空行、`split("=",1)`），属真实重复
- `runner._maybe_load_dotenv` 硬编码 `Path("D:/code/mcs/.env")`（开发者本机路径），换机即失效；改由 `bench/_env.py` 用 `__file__` 推导项目根，与 `scripts/_common.PROJECT_ROOT` 同口径

**替代方案：**

1. **引入 `python-dotenv`**：新增依赖，而当前解析仅 9 行，不值当
2. **仅删 runner 硬编码、不提取公共函数**：留下两份重复解析

**实现方式：**

- `load_dotenv(env_file=None)`：`None` → 项目根 `.env`；文件不存在返回 `False`；解析语义同前
- `_common.setup_env`：`load_dotenv(PROJECT_ROOT / ".env")`，保留 stdout UTF-8 + `DEEPSEEK_MODEL` / `MCS_NO_SUMMARY_REGEN`
- `runner._maybe_load_dotenv`：`if not load_dotenv(): load_dotenv(Path(".env"))`（项目根优先、当前目录兜底，等价原两层查找）

**Non-Goal：** 不为 `data.py` 数据路径引入环境变量配置（如 `MULTIHOP_CORPUS_PATH`）——`data.py` 已用相对路径 `Path(__file__).resolve().parent / "data" / ...`，硬编码本机路径问题不存在。

---

## Risks / Trade-offs

### Risk 1: MCSBuilder.build() 流程变更导致测试失败

**风险：** 如果未来 MCSBuilder.build() 流程调整，测试可能需要同步修改

**缓解：**

- 这是预期行为，测试应跟随主代码变化
- 继承模式确保测试与主代码保持同步

### Risk 2: 插件初始化 helper 过度通用化

**风险：** 提取的 helper 可能不适应所有场景

**缓解：**

- 保留 helper 的参数灵活性（config 可选、extra_plugins 可选）
- 不强制所有测试使用 helper，复杂场景可自行初始化

---

## Migration Plan

### 阶段 1: 测试基础设施重构

1. 修改 `tests/conftest.py`：
   - 将 `_MockLLMBuilder` 重构并重命名为公开 `MockLLMBuilder`，继承 MCSBuilder
   - 添加 `init_plugin_manager()` helper
   - 添加 `fanout_reducer` factory fixture（支持 `token_budget` 参数化）

2. 更新依赖 conftest 的测试文件：
   - `test_pipeline_write.py`：删除 `_build_mcs_with_store`
   - `test_pipeline_query.py`：删除 `_build_engine`
   - `test_dual_edge.py`：删除 `_build_engine`
   - `test_hub_fallback.py`：删除 `_init`
   - `test_directed_navigation.py`：删除 `_init_plugin`
   - `test_directed_hierarchy.py`：删除 `_fanout_with_root`
   - `test_seed_graph.py`：删除 `_fanout_with_root`
   - `test_anti_regression.py`：删除 `_fanout_with_root`

3. 运行测试验证重构正确性

### 阶段 2: 过期代码清理

1. 删除 `_run_eval_variants.py`（已于 `236bd58` 删除，本 change 确认）
2. 更新相关文档（如有引用）

### 阶段 3: bench .env 加载去重

1. 新建 `bench/_env.py`（`load_dotenv`）
2. `scripts/_common.setup_env` 复用 `load_dotenv`
3. `runner._maybe_load_dotenv` 复用 `load_dotenv`，删硬编码 `D:/code/mcs/.env`
4. 新增 `tests/test_bench_env.py` 覆盖边界场景

---

## Open Questions

1. **是否需要为 MockLLMBuilder 支持自定义 TokenBudget 配置？**
   - 当前设计使用 config 中的 token_budget
   - 如需测试边界场景，可在 config 中设置

**已决（原 Open Question 2）**：`fanout_reducer` fixture 需做成 factory、支持 `token_budget` 参数化 —— 实际调用中 `test_seed_graph` 同时使用 `TokenBudget(500)` 与 `TokenBudget(8000)`（`test_directed_hierarchy` 仅用 500），固定值无法覆盖。原先考虑的 `extra_cfg` 参数化基于 `test_anti_regression._fanout_with_root` 的 `**extra_cfg` 签名，但核实调用点发现该函数是未被调用的死定义，故 `extra_cfg` 非真实需求，不再纳入。
