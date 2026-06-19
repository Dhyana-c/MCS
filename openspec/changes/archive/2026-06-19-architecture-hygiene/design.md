# 设计说明 — architecture-hygiene

## 背景与判据

探查结论：核心库分层健康，**不做结构性重构**。本 change 只清三处局部债务，统一判据是**行为保持**——纯移动 + 改 import + 文档同步，运行时行为逐字不变，由现有测试套件兜底（迁移后必须全绿）。

## 决策 1：MCP server 移到顶层 `mcs_mcp/`，而非收进库内 `mcs/agent/`

两个候选：

| 方案 | 布局 | 取舍 |
|------|------|------|
| **A（采用）** 应用包都作 `mcs/` 的**兄弟** | `mcs/`(纯库) · `mcs_mcp/` · `mcs_agent/` · `bench/` | 与既有 `mcs_agent` 顶层独立化**先例一致**；`import mcs` 彻底不含应用代码；库/应用边界清晰 |
| B 应用都**收进** `mcs/` | `mcs/mcp/` · `mcs/agent/` | 与 `mcs_agent` 现状冲突（需把它搬回来，churn 更大）；库里塞应用代码，可选依赖（fastapi/mcp）渗入库命名空间 |

选 A：`mcs_agent` 已经定下了"应用作顶层兄弟包"的范式，把 `mcs.mcp` 拉出来对齐它，是 churn 最小、方向最一致的选择。`mcs/` 自此是纯库。

## 决策 2：共享渲染落在 `mcs/rendering.py`（库内），不在任一应用包

两应用（`mcs_mcp`、`mcs_agent`）现在都只依赖核心库 `mcs`，所以**唯一合法的共享位置是核心库**。函数依赖链：

```
mcs_mcp.server  ┐
                ├─► mcs.rendering ─► mcs.core.context_renderer
mcs_agent.memory┘                    mcs.entities.graph
```

- 放 `mcs/rendering.py`（顶层库模块）而非 `mcs/utils/`：`utils` 约定为叶子（不反向依赖 core），而这两个函数依赖 `ContextRenderer`，放 utils 会造成 `utils → core` 的层级倒置。顶层 `mcs.rendering` 可正当依赖 core，无环。
- 不并入 `core/context_renderer.py`：`ContextRenderer` 是"渲染节点/事实供 LLM 上下文"的引擎组件；这两个函数是"把 query/ingest **结果**转人/LLM 可读文本"的更高层展示helper，调用 `render_facts`。职责不同，分模块更清晰。
- 去下划线转公开：`_render_query_result` → `render_query_result`、`_format_ingest_status` → `format_ingest_status`。既然要被两个包正当引用，就不该是私有名。签名保持不变：
  - `render_query_result(result, relation_model, plugin_manager) -> str`
  - `format_ingest_status(wctx) -> str`

## 决策 3：硬迁移，不留 `mcs.mcp` 兼容 shim

项目处 Phase 1（`0.1.0`），全仓 grep 确认 `mcs.mcp` 无任何**外部/下游**消费者（仅本仓 agent/tests/docs 引用，均在本 change 内一并更新）。留 shim（如 `mcs/mcp/__init__.py` re-export `mcs_mcp`）只会把刚移走的代码又焊回库里、违背决策 1 的"纯库"目标。故采用硬迁移：

- `mcs-mcp` **console 入口名保持不变**（用户可见命令不变），仅其 target 改 `mcs_mcp.server:main`。
- `python -m mcs.mcp` → `python -m mcs_mcp`（这是用户可见变更，需同步 README / docs/mcp-server.md）。

## 决策 4：插件归位是"修复违规"，非新增契约

`plugin-directory-by-type` spec 已要求"import 路径反映插件类型"。`SemanticTrimPlugin`（`TrimPlugin`）住在 `seed_selector/` 本就违规。迁到 `plugins/trim/` 是把代码改回**符合既有契约**，故只登记为任务、不产生 spec delta。`mcs/plugins/seed_selector/` 清空后移除目录。

## 迁移顺序（降低中间态破坏）

1. 先建 `mcs/rendering.py`（公开函数），让 `mcs/mcp/server.py` 与 `mcs_agent/memory.py` 改为从它导入并跑通测试 —— 此步即斩断 `mcs_agent → mcs.mcp` 私有耦合。
2. 再把 `mcs/mcp/` 整体迁 `mcs_mcp/`，更新 `pyproject` 入口/打包、docs、tests 的路径。
3. 插件归位 + 注册表 import 更新。
4. 同步 `docs/architecture.md`。
5. 全量 `pytest -q` + 入口启动冒烟。

每步独立可验证；任一 import 遗漏在导入期即时报错，不会静默。

## 非目标（Non-goals）

- 不删任何废弃 API（`preprocess_plugin` stub、`store` 三个 deprecated 方法、`attach_statement`）——破坏性，单列后续 change。
- 不移动 `mcs_agent`（已在目标位置）。
- 不改任何运行时行为、不调 token 预算/不变量逻辑。
- 不重组 spec 颗粒度（治理问题，另议）。
