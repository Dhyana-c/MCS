## Context

### 当前状态

测试代码中存在多处重复的构建/初始化逻辑：

1. **`tests/conftest.py:_MockLLMBuilder.build()`**（行 171-263）
   - 创建动态 `_MockBuilder` 子类继承 `MCSBuilder`
   - 但 `build()` 方法完全重写，没有调用 `super().build()`
   - 手动组装 Store → TokenBudget → PluginManager → 插件注册 → 初始化 → 管线构建 → MCS

2. **`tests/test_pipeline_write.py:_build_mcs_with_store()`**（行 405-518）
   - 手动组装，支持外部传入 SQLiteStore
   - 与 MCSBuilder.build() 逻辑高度重复

3. **`tests/test_mcs_api.py:_build_mcs()`**（行 40-98）
   - 简化版手动组装

4. **`tests/test_hub_fallback.py:_init()`、`tests/test_directed_navigation.py:_init_plugin()`**
   - 相同的 PluginManager + PluginContext 初始化模式

5. **`tests/test_directed_hierarchy.py` 和 `tests/test_seed_graph.py` 的 `_fanout_with_root()`**
   - 完全相同的代码

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
4. 提取 bench 脚本的公共 `.env` 加载逻辑
5. 修复 `bench/multihop_rag/data.py` 硬编码路径
6. 删除过期脚本 `_run_eval_variants.py`

**Non-Goals:**

- 不修改 MCSBuilder 或 Phase1Builder 的核心逻辑
- 不引入新的外部依赖（如 python-dotenv）
- 不修改 bench 的评测逻辑

---

## Decisions

### Decision 1: _MockLLMBuilder 正确继承 MCSBuilder

**选择：** 让 `_MockLLMBuilder` 创建的动态子类调用 `super().build()`

**理由：**

- `MCSBuilder.build()` 已封装完整的 14 步流程
- 测试构建器只需覆写 `get_plugin_class()` 返回 MockLLM
- 复用父类逻辑可避免测试代码与主代码不同步

**替代方案：**

1. **不继承，保持现状**：测试代码与主代码分叉，未来维护成本高
2. **提取 Builder 基类**：过度设计，MCSBuilder 已经是抽象基类

**实现方式：**

```python
class _MockLLMBuilder:
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

### Decision 2: 提取插件初始化 helper

**选择：** 在 `tests/conftest.py` 添加 `init_plugin_manager()` 函数

**理由：**

- `_init()` 和 `_init_plugin()` 的差异仅是 `config=None` vs `config=MCSConfig()`
- 统一后可减少重复代码

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
```

### Decision 3: bench 脚本 .env 加载提取

**选择：** 创建 `bench/_env.py` 提供 `load_dotenv()` 函数

**理由：**

- 6 个脚本包含完全相同的 .env 加载代码
- 不引入 python-dotenv 依赖（保持零外部依赖）

**实现方式：**

```python
# bench/_env.py
from pathlib import Path
import os

def load_dotenv(env_file: Path | None = None) -> None:
    """加载 .env 文件到环境变量。"""
    if env_file is None:
        # 默认从项目根目录加载
        env_file = Path(__file__).parent.parent / ".env"

    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
```

### Decision 4: 硬编码路径修复

**选择：** 使用环境变量 + 相对路径作为默认值

**理由：**

- 硬编码 `D:\code\hotpot\...` 只在开发者本机有效
- 环境变量允许 CI/CD 和其他开发者自定义路径

**实现方式：**

```python
# bench/multihop_rag/data.py
import os
from pathlib import Path

# 项目根目录下的 data/ 目录作为默认位置
_BENCH_ROOT = Path(__file__).parent.parent
_PROJECT_ROOT = _BENCH_ROOT.parent

DEFAULT_CORPUS = os.environ.get(
    "MULTIHOP_CORPUS_PATH",
    str(_PROJECT_ROOT / "data" / "multihoprag_corpus.json")
)
DEFAULT_QA = os.environ.get(
    "MULTIHOP_QA_PATH",
    str(_PROJECT_ROOT / "data" / "multihoprag_qa.json")
)
```

### Decision 5: 删除过期脚本

**选择：** 删除 `_run_eval_variants.py`

**理由：**

- 功能已被 `bench/multihop_rag/scripts/` 下脚本覆盖
- 硬编码路径、环境变量 hack、位置异常
- 以 `_` 开头暗示临时/实验性文件

---

## Risks / Trade-offs

### Risk 1: MCSBuilder.build() 流程变更导致测试失败

**风险：** 如果未来 MCSBuilder.build() 流程调整，测试可能需要同步修改

**缓解：**

- 这是预期行为，测试应跟随主代码变化
- 继承模式确保测试与主代码保持同步

### Risk 2: 硬编码路径修复影响现有用户

**风险：** 现有开发者可能依赖旧路径

**缓解：**

- 通过环境变量 `MULTIHOP_CORPUS_PATH` 保持兼容
- 在 `bench/multihop_rag/README.md` 文档化新的路径配置方式

### Risk 3: 插件初始化 helper 过度通用化

**风险：** 提取的 helper 可能不适应所有场景

**缓解：**

- 保留 helper 的参数灵活性（config 可选、extra_plugins 可选）
- 不强制所有测试使用 helper，复杂场景可自行初始化

---

## Migration Plan

### 阶段 1: 测试基础设施重构

1. 修改 `tests/conftest.py`：
   - 重构 `_MockLLMBuilder` 继承 MCSBuilder
   - 添加 `init_plugin_manager()` helper
   - 添加 `fanout_with_root()` fixture

2. 更新依赖 conftest 的测试文件：
   - `test_pipeline_write.py`：删除 `_build_mcs_with_store`
   - `test_pipeline_query.py`：删除 `_build_engine`
   - `test_mcs_api.py`：删除 `_build_mcs`
   - `test_hub_fallback.py`：删除 `_init`
   - `test_directed_navigation.py`：删除 `_init_plugin`
   - `test_directed_hierarchy.py`：删除 `_fanout_with_root`
   - `test_seed_graph.py`：删除 `_fanout_with_root`

3. 运行测试验证重构正确性

### 阶段 2: bench 脚本优化

1. 创建 `bench/_env.py`
2. 更新 6 个 bench 脚本使用 `load_dotenv()`
3. 修复 `bench/multihop_rag/data.py` 硬编码路径

### 阶段 3: 过期代码清理

1. 删除 `_run_eval_variants.py`
2. 更新相关文档（如有引用）

---

## Open Questions

1. **是否需要为 MockLLMBuilder 支持自定义 TokenBudget 配置？**
   - 当前设计使用 config 中的 token_budget
   - 如需测试边界场景，可在 config 中设置

2. **`fanout_with_root()` fixture 是否应支持参数化？**
   - 当前实现固定使用 `FanoutReducerPlugin({"floor": 16})`
   - 如需测试不同参数，可扩展为 factory fixture
