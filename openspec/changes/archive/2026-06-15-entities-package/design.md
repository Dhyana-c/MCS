## Context

`mcs.core` 当前是"实体 + 服务 + 契约 + 异常 + 值对象"的大杂烩。纯数据模型（`Node`/`Edge`/`Subgraph`、`Decision` 系列、`MCSConfig`）与引擎逻辑（`MCS`/`WritePipeline`/`QueryEngine`/`ContextRenderer`）、契约（`StoreInterface`/`Plugin`）、含逻辑的值对象（`TokenBudget`）、异常（`errors`）混居。这三类数据模型被全仓 ~50+ 处 import。

本次是**纯结构性重构**：把纯数据模型抽到 `mcs.entities`，物理隔离实体层与服务层，零运行时行为变更。后续 Phase 2 实体（事件层、版本、置信度）将落在 `entities` 而非继续堆进 `core`。

约束（来自 `CLAUDE.md`）：最小改动；保持默认基线行为不变；核心代码绝对正确；测试须跑。

## Goals / Non-Goals

**Goals:**
- 新建 `mcs/entities/` 包，承接全部纯数据模型（`graph` / `decisions` / `config` 三模块）。
- 实体内容**逐字不变**（dataclass 字段、常量值、classmethod 逻辑原样搬）。
- 全量迁移所有引用方 import 路径，删除旧 `mcs.core.{graph,decisions,config}`，不留兼容层。
- 清理 `graph.py` 的死代码（`StoreInterface` re-export + `GraphStoreInterface` 别名），让实体包不反向依赖 `core.store`。
- 全量 `pytest -q` 绿 + `ruff check .` 零错 + `python -c "import mcs"` 成功。

**Non-Goals:**
- 不改任何 dataclass 字段、API 签名、运行时行为、不变量。
- 不搬异常（`errors.py`）、不搬 `TokenBudget`、不搬 `StoreInterface`/`Plugin`/`PluginManager`、不搬任何服务类。
- 不修正 `project-skeleton` spec 中本就过时的内容（如 `GraphStore`/`Edge.direction` 这些与现状不符的旧描述）——只改本次涉及的路径绑定。
- 不处理 `_review_diff.txt`、`mcs.egg-info`（前者临时文件，后者 `pip install -e .` 自动重生）。

## Decisions

### D1: 实体范围 = 仅纯 dataclass（不含异常/契约/TokenBudget）

**决策**：只迁 `graph`（`Node`/`Edge`/`Subgraph`）、`decisions`（`ConceptDraft`/`Decision`/`DecisionList`/`Community`/`MultiHubDecision`/`ActionType`）、`config`（`MCSConfig` + `PHASE1_*` 常量）。

**Alternatives**：
- *(否决)* 连异常一起搬：异常常被视为"领域实体"，但本仓异常是通用管道错误（`LLMParseError`/`ConfigurationError`），与领域实体耦合弱；且迁异常会牵动 `prompts`/`core` 全链路，放大改动。用户已选定"仅纯数据模型"。
- *(否决)* 连 `Plugin`/`StoreInterface` 契约一起搬：契约是"被多方依赖的接口"，留 `core` 更符合"`core` = 引擎与契约中枢"的直觉；搬走会割裂"接口在 core、实现在 plugins/stores"的现状。

### D2: `TokenBudget` 留 `core`（归服务）

**决策**：`TokenBudget` 不进 `entities`。

**理由**：它虽持有配置值 `T`，但 `estimate_*` 方法是核心估算逻辑，且延迟 `import ContextRenderer`，是"带行为的服务对象"而非纯数据模型。拆分（配置归实体、估算留服务）会肢解一个紧耦合的类，违背最小改动。

**Alternative**：*(否决)* 拆 `TokenBudget` 为 `TokenBudgetConfig`（实体）+ `TokenEstimator`（服务）——改动大、收益低，且违反"逐字不变"目标。

### D3: 包结构 = `mcs/entities/{graph,decisions,config}.py`

**决策**：沿用现有三文件粒度，不合并、不新增子目录。

**理由**：最小改动；保持每个文件职责单一；`__init__.py` 汇总 re-export 供 `from mcs.entities import Node` 便捷导入。

**Alternative**：*(否决)* 单文件 `mcs/entities.py` 平铺——与"为后续扩展"初衷相悖，且文件过大。

### D4: 全量迁移，删旧路径，不留 re-export 兼容层

**决策**：`mcs.core.{graph,decisions,config}` 三个旧模块删除，所有引用一次性改到 `mcs.entities.*`。

**理由**：用户已选定"全量迁移，删旧路径"。本仓无外部下游消费者（`pip install -e .` 本地开发），不欠兼容债。留 re-export 会留下"实体到底在哪"的歧义，与重构初衷相悖。

**Trade-off**：改动面大（~50+ 处），但都是机械替换；用 `pytest` + `ruff`（`I` 规则）兜底，风险可控。

### D5: 清理 `graph.py` 死代码

**决策**：迁移时移除 `entities/graph.py` 末尾两行——`from mcs.core.store import StoreInterface`（re-export）与 `GraphStoreInterface = StoreInterface`（别名）。

**证据**：全仓 grep（排除 `.venv`）确认源码中**无** `from mcs.core.graph import StoreInterface`、**无** `from mcs.core.graph import GraphStoreInterface` 的实际引用；仅 `openspec/changes/archive/`、`CHANGELOG.md`、`_review_diff.txt` 历史提及。

**收益**：`entities.graph` 不反向依赖 `core.store`，实体包纯净（只含 dataclass）。

### D6: 迁移映射表

| 旧路径 | 新路径 | 内容（逐字不变） |
|---|---|---|
| `mcs.core.graph` | `mcs.entities.graph` | `Node`, `Edge`, `Subgraph`（**移除** `StoreInterface` re-export + `GraphStoreInterface` 别名） |
| `mcs.core.decisions` | `mcs.entities.decisions` | `ConceptDraft`, `Decision`, `DecisionList`(别名), `Community`, `MultiHubDecision`, `ActionType` |
| `mcs.core.config` | `mcs.entities.config` | `MCSConfig`, `PHASE1_SHARED_PLUGINS`, `PHASE1_WRITE_PLUGINS`, `PHASE1_READ_PLUGINS`, `PHASE1_DEFAULT_PLUGINS`, `_add_llm_config` |

**特殊照顾**：`mcs/plugins/maintenance/fanout_reducer.py` 有 `from mcs.core.graph import Node as GraphNode`（带 `as` 别名），替换时保留别名、只改路径。

## 依赖方向（迁移后）

```
entities.graph       ──(无依赖，纯 dataclass)
entities.decisions   ──(无依赖，纯 dataclass)
entities.config      ──(延迟 import prompts.judge_relations_attr，在 classmethod 内)
core.token_budget    ──→ entities.graph (TYPE_CHECKING)
core.{mcs,builder,query_engine,write_pipeline,context_renderer} ──→ entities.*
prompts.{judge_relations*,extract_concepts,decide_hub,...}      ──→ entities.decisions + core.errors
stores.{in_memory,sqlite_store}  ──→ core.store + entities.graph
interfaces/*         ──→ entities.graph (类型标注)
```

**循环依赖检查**：`entities.config` →（classmethod 内延迟）`prompts.judge_relations_attr` → `entities.decisions` + `core.errors`。`prompts` 不 import `entities.config`，无环。`entities` 三模块互不 import。✓

## Risks / Trade-offs

- [机械漏改 import → ImportError] → 全量 `pytest -q`（覆盖 ~25 测试文件）+ `ruff check .`（`I` 规则捕获错误/未用 import）+ 干净环境 `python -c "import mcs"`。
- [`fanout_reducer` 的 `as GraphNode` 别名漏改] → 单独列出，逐处核对。
- [`mcs/__init__.py` 导出 `MCSConfig` 的路径漏改 → 顶层 import 崩] → 该文件单测 `python -c "import mcs"` 直接暴露。
- [迁移引入循环 import] → design 已分析无环；迁移后跑测试验证。
- [Trade-off] 无兼容层 = 外部若有人 `from mcs.core.graph import Node` 会断；本仓无此下游，可接受。

## Migration Plan

1. 建包：新建 `mcs/entities/__init__.py`（汇总 re-export）、`graph.py`、`decisions.py`、`config.py`。
2. 搬运：把三个文件内容逐字搬入（`config.py` 保留 classmethod 内的延迟 import 不变；`graph.py` 去 D5 死代码）。
3. 删旧：删除 `mcs/core/{graph,decisions,config}.py`。
4. 改 import：按目录分批替换 `mcs.core.{graph,decisions,config}` → `mcs.entities.{graph,decisions,config}`（core / stores / plugins / prompts / interfaces / diagnostics / presets / 顶层 `__init__.py` / tests / examples / bench）。
5. 更新 `mcs/core/__init__.py` docstring（模块清单移除三模块，注明已迁 `entities`）。
6. 更新 `README.md`、`docs/architecture.md` §8 目录树。
7. 验证：`.venv\Scripts\python.exe -m pytest -q` 全绿；`ruff check .` 零错；`python -c "import mcs"` 成功。

**回滚**：未提交前 `git checkout .` + 删除新建的 `entities/` 目录即可（纯移动，无数据迁移）。

## Open Questions

- 无。4 个关键决策（实体范围 / TokenBudget 归属 / 包结构 / 兼容策略）已与用户确认。
