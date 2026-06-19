## Why

整体架构（`entities → core → interfaces → plugins/stores → presets`）分层干净、依赖单向，**无需结构性重构**。但探查发现三处局部结构债务，影响可维护性与新人上手：

1. **应用层包不对称 + 跨应用私有耦合**：`mcs_agent` 已是顶层独立包（见 `memory-agent` 包独立化），但 MCP server 仍内嵌在核心库 `mcs/mcp/`。两个本质同级的应用包位置不一致；更糟的是 `mcs_agent/memory.py` 直接 `from mcs.mcp.server import _render_query_result, _format_ingest_status` —— **跨应用借用另一个应用的下划线私有函数**。该耦合还被 `memory-agent` spec 第 25 行**显式固化**为契约（"SHALL 复用 `mcs.mcp.server._render_query_result`"）。这两个函数文档自述"不依赖 mcp SDK 的纯函数"，本质是**共享展示逻辑**，放错了包。

2. **插件位置违反 `plugin-directory-by-type` 契约**：`SemanticTrimPlugin` 是 `TrimPlugin`（`PluginType.TRIM`），却住在 `mcs/plugins/seed_selector/llm_seed_selector.py`。该目录对应已废弃的 seed-selector 能力，import 路径未反映插件真实类型。

3. **理解性文档漂移**：`docs/architecture.md` 的"目录结构"段描述 `plugins/base.py`、`plugins/phase1/`、`plugins/phase2/`、`interfaces/storage.py` —— **均不存在**。实际为 `plugins/` 按类型分目录、Plugin 基类在 `core/plugin.py`、StoreInterface 在 `core/store.py`。

> **范围界定**：本 change 仅做**行为保持型**结构清理（纯移动 + 改 import + 文档同步），不改任何运行时行为。废弃 API 删除（`interfaces/preprocess_plugin.py` stub、`store` 的 `get_neighbors`/`get_out_neighbors`/`get_edge`、`attach_statement` no-op）是**破坏性变更**，单列为后续 change 评审，**不在本提案内**。

## What Changes

### 1. 应用层包重组：MCP server 移出核心库

- 把 `mcs/mcp/` 整体迁为顶层包 `mcs_mcp/`（与 `mcs_agent/` 对称，`mcs/` 回归纯库）。
- `pyproject.toml`：console 入口 `mcs-mcp` 目标由 `mcs.mcp.server:main` 改为 `mcs_mcp.server:main`；packages.find 显式纳入 `mcs_mcp*`。
- 启动方式 `python -m mcs.mcp` → `python -m mcs_mcp`（`mcs-mcp` console 名不变）。
- 同步 `README.md`、`docs/mcp-server.md`、`tests/test_mcp_server.py` 的 import 与启动指令。
- **行为不变**：MCP 仍 stdio 传输、`mcp`/`PyYAML` 仍 `[mcp]` 可选依赖；`import mcs` 不再触及 mcp（隔离更彻底）。

### 2. 抽取共享渲染纯函数到核心库

- 新建 `mcs/rendering.py`，承载 `render_query_result(result, relation_model, plugin_manager)` 与 `format_ingest_status(wctx)`（去下划线、转为公开 API）。两者仅依赖 `mcs.core.context_renderer` 与 `mcs.entities.graph`，依赖方向 `rendering → core`（无环）。
- `mcs_mcp.server` 与 `mcs_agent.memory` **均从 `mcs.rendering` 导入**，删除各自重复/私有引用。
- 消除 `mcs_agent → mcs_mcp` 的跨应用依赖：两应用只依赖核心库。

### 3. 归位错放的插件

- 把 `SemanticTrimPlugin` 从 `mcs/plugins/seed_selector/` 迁到 `mcs/plugins/trim/`（其真实类型 `PluginType.TRIM`）。
- 更新 `mcs/presets/phase1.py` 注册表 import 路径。
- `mcs/plugins/seed_selector/` 空目录随之移除。

### 4. 文档同步

- 修正 `docs/architecture.md` 的"目录结构"段，使其反映真实布局（by-type plugins、`core/plugin.py`、`core/store.py`、`mcs_mcp/` 与 `mcs_agent/` 顶层应用包）。

## Capabilities

### New Capabilities

- `result-rendering`: 核心库共享的查询/写入结果渲染纯函数（`mcs/rendering.py`），供 `mcs_mcp` 与 `mcs_agent` 复用，杜绝跨应用私有引用。

### Modified Capabilities

- `mcp-server`: MCP server 改为顶层包 `mcs_mcp`，渲染委托 `result-rendering`；入口 `mcs-mcp` 指向 `mcs_mcp.server:main`、`python -m mcs_mcp`。
- `memory-agent`: `MemoryStore` 渲染改为复用 `result-rendering` 的公开函数，不再引用 `mcs.mcp.server` 私有函数。

> `plugin-directory-by-type` 契约**不变**——插件归位是把违规代码改回**符合既有契约**，仅登记为任务、无 spec delta。`docs/architecture.md` 为理解性文档（非 capability spec），同样仅登记任务。

## Impact

### 代码变更

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `mcs/mcp/` → `mcs_mcp/` | 移动 | 整目录迁为顶层包（`__init__.py`/`__main__.py`/`server.py`） |
| `mcs/rendering.py` | 新增 | `render_query_result` / `format_ingest_status` 公开纯函数 |
| `mcs_mcp/server.py` | 修改 | 删内联 `_render_*`，改从 `mcs.rendering` 导入；`python -m` 文案 |
| `mcs_agent/memory.py` | 修改 | import 改 `from mcs.rendering import ...`，删 `mcs.mcp.server` 引用 |
| `mcs/plugins/trim/llm_seed_selector.py` | 移动 | `SemanticTrimPlugin` 从 `seed_selector/` 迁入 |
| `mcs/plugins/seed_selector/` | 删除 | 空目录移除 |
| `mcs/presets/phase1.py` | 修改 | `semantic_trim` 注册表 import 路径更新 |
| `pyproject.toml` | 修改 | console 入口目标 + packages.find 纳入 `mcs_mcp*` |
| `docs/architecture.md` | 修改 | "目录结构"段同步真实布局 |
| `docs/mcp-server.md` / `README.md` | 修改 | `python -m mcs.mcp` → `python -m mcs_mcp` |
| `tests/test_mcp_server.py` | 修改 | import 与 `python -m` 路径更新 |

### 依赖关系

- `mcs_mcp` / `mcs_agent` → `mcs`（核心库，含新 `mcs.rendering`）；两应用间**不再相互依赖**。
- 核心库 `mcs` 不依赖任何应用包，方向单一。

### 风险

- **中风险**：import 路径与入口点 churn 面较广（pyproject / docs / tests / 两应用包）；遗漏一处会在导入或启动时即时暴露（非静默）。
- **低风险**：渲染函数与插件归位均为纯移动，逻辑逐字不变。
- **无外部消费者**：项目处 Phase 1（`version 0.1.0`），`mcs.mcp` 无下游依赖，采用硬迁移、不留兼容 shim（见 design.md 决策）。
- **需验证**：迁移后 `pytest tests/ -q` 全绿；`python -m mcs_mcp --help`（装 `[mcp]`）与 `mcs-mcp` 入口可启动。
