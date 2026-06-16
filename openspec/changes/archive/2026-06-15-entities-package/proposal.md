## Why

当前 `mcs.core` 同时承载**纯数据模型**（`Node`/`Edge`/`Subgraph`、`Decision`/`ConceptDraft`/`Community`、`MCSConfig`）与**服务/契约**（`MCS`/`WritePipeline`/`QueryEngine`/`ContextRenderer`/`TokenBudget`/`StoreInterface`/`Plugin`）。实体与服务混在一个包里，违背"core 是引擎逻辑"的直觉；且后续要扩展更多领域实体（Phase 2 事件层、版本、置信度等数据模型）时，`core` 会持续臃肿、实体无家可归。

把**纯数据模型**抽到独立 `mcs.entities` 包，让实体层与服务层物理分离，为后续实体扩展提供清晰落点。本次只搬数据模型，不改任何运行时行为。

## What Changes

- **新建 `mcs/entities/` 包**，内含 `graph.py` / `decisions.py` / `config.py` 三个模块（沿用现有文件粒度），加 `__init__.py` 汇总 re-export。
- **迁移纯数据模型**（`mcs.core` → `mcs.entities`，逐字不变）：
  - `graph.py`：`Node` / `Edge` / `Subgraph`
  - `decisions.py`：`ConceptDraft` / `Decision` / `DecisionList`（类型别名）/ `Community` / `MultiHubDecision` / `ActionType`
  - `config.py`：`MCSConfig` + `PHASE1_SHARED_PLUGINS` / `PHASE1_WRITE_PLUGINS` / `PHASE1_READ_PLUGINS` / `PHASE1_DEFAULT_PLUGINS` 常量 + `_add_llm_config`
- **清理 `graph.py` 死代码**：移除末尾 `from mcs.core.store import StoreInterface` 的 re-export 与 `GraphStoreInterface = StoreInterface` 兼容别名（全仓 grep 确认源码无人经 `mcs.core.graph` 取它们，仅 archive spec / CHANGELOG 历史提及）。使 `entities.graph` 不反向依赖 `core.store`，实体包保持纯净。
- **BREAKING**（针对 import 路径）：删除 `mcs.core.graph` / `mcs.core.decisions` / `mcs.core.config` 三个旧模块，**不留 re-export 兼容层**；全量迁移所有引用方到 `mcs.entities.*`。
- **留在 `mcs.core` 不动**：`mcs.py`、`builder.py`、`query_engine.py`、`write_pipeline.py`、`context_renderer.py`、`store.py`（`StoreInterface`）、`plugin.py`、`plugin_manager.py`、`token_budget.py`（`TokenBudget`，含估算逻辑、归服务）、`errors.py`（异常）。
- **更新入口与文档**：`mcs/__init__.py` 的 `MCSConfig` import、`mcs/core/__init__.py` 模块清单 docstring、`README.md` 示例 import、`docs/architecture.md` §8 目录树。

## Capabilities

### New Capabilities
- `entities-package`: 实体包 `mcs.entities` 的职责边界与归类规则——哪些是实体（纯数据模型，进 entities）、哪些不是（服务/契约/异常/含逻辑的值对象如 `TokenBudget`，留 core），为后续 Phase 2 实体扩展提供落点。

### Modified Capabilities
- `project-skeleton`: 目录结构 scenario 与核心引擎骨架 scenario 中绑定 `mcs.core.graph` / `mcs.core.config` 的路径断言，随实体迁移更新为 `mcs.entities.graph` / `mcs.entities.config`；目录树新增 `entities/` 子包。

## Impact

- **代码 import 路径**：约 50+ 处引用需从 `mcs.core.{graph,decisions,config}` 迁移到 `mcs.entities.{graph,decisions,config}`，涉及 `mcs/core`（内部 7 文件）、`mcs/stores`（2）、`mcs/plugins`（~11）、`mcs/prompts`（4）、`mcs/interfaces`（8，类型标注）、`mcs/diagnostics`（1）、`mcs/presets`（1）、`mcs/__init__.py`、`tests/`（~25）、`examples/`（2）、`bench/`（2）。其中 `mcs/plugins/maintenance/fanout_reducer.py` 有 `import Node as GraphNode` 别名需单独照顾。
- **文档**：`README.md`、`docs/architecture.md` §8 目录树。
- **运行时行为**：零变化（纯文件移动 + import 路径替换）；契约、API、不变量均不变。
- **风险**：机械重构漏改 import → `ImportError`/`ModuleNotFoundError`；缓解=全量 `pytest -q` + `ruff check .`（I 规则会捕获未用/错误 import）+ 干净环境 `python -c "import mcs"`。
- **依赖方向**：迁移后依赖为 `entities → {prompts(仅 config 的 classmethod 内延迟 import), core.errors}`；`core → entities`（服务消费数据模型）。无循环：`prompts` 只 import `entities.decisions` + `core.errors`，不 import `entities.config`。
