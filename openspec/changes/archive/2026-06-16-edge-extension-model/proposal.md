## Why

MCS 要作为**框架**交付，有两个使用场景——**作为依赖库**（用户写 Python、在代码里登记扩展）与**未来做成 MCP server**（用户配置一个服务）。两种场景下系统都"提供框架与基本功能、允许用户在框架下扩展"。扩展面三样：**加插件、改 prompt、定制节点（含边）**。

经确认采 **A 方案**：节点 / 边的"定制" = **加字段**；**核心算法行为（裂变如何分组、概念如何抽、关系如何判）由 prompt 控制**，不让用户改框架代码、不暴露与核心不变量相关的旋钮。框架决定"何时"（何时触发裂变 / 截断），prompt 决定"如何"。

现状盘点（逐条对源码核对、属实，决定本变更只补缺口、不重建）：

- **节点已可扩展**：`Node.extensions` + `NodeExtensionInterface`（`render(node, purpose)` 返回 `None` 即不贡献）（[node_extension.py:52](mcs/interfaces/node_extension.py:52)）；`nodes` 表已有 `extensions_json` 列（[sqlite_store.py:565](mcs/stores/sqlite_store.py:565)）。
- **插件已可扩展**：`register_plugin / register_shared_plugin / unregister_plugin`（代码登记）。
- **prompt 已可覆盖**：`prompt_overrides` + `register_prompt`；驱动核心的 `decide_hub / extract_concepts / judge_relations` 均在可覆盖清单（[prompts/__init__.py:25](mcs/prompts/__init__.py:25)）——**A 方案前提成立，"用 prompt 控制核心语义"今天即可用**。
- **缺口（本变更针对）**：
  1. **边不可扩展**——`Edge` 是固定数据类、无 `extensions`（[graph.py:30](mcs/entities/graph.py:30)）；`edges` 表无扩展列（[sqlite_store.py:573](mcs/stores/sqlite_store.py:573)）；存储 schema 扩展只管 `nodes`。
  2. **`priority` 是存储原语、非派生**——应由创建时间、活跃数等扩展字段算出。
  3. **库不记录建库出处**——`relation_model` 未持久化，打包后易"混库静默损坏"（宪法：混库为未定义行为）。

本变更是**阶段 2（遗忘降权）的地基**：创建时间、活跃数等字段要能挂到点 / 边上，优先级 / 衰减分由这些字段派生。

## What Changes

- **新增 `EdgeExtensionInterface`**（镜像 `NodeExtensionInterface`）+ `PluginType.EDGE_EXTENSION`：边获得 `extensions` 槽；`schema/default/serialize/deserialize` + `render(edge, purpose) -> str | None`。
- **`Edge` 增 `extensions` 字段**；`edges` 表增 `extensions_json` 列；store 逐条保真编解码；**两端反查返回的同一边对象带完整 extensions**。**重组（fanout 合并迁移）MUST 保真复制 extensions**——现 `_migrate_edges` 只复制 `kind/label/priority`（[fanout_reducer.py:690](mcs/plugins/maintenance/fanout_reducer.py:690)），会丢扩展数据。
- **字段级可见性（渲染侧）**：`render(..., purpose)` 返回 `None` = 该 purpose 下隐藏、不渲染。边渲染函数 `render_fact_edge` / `render_assoc_edge` 现**无 `purpose` 参**（[context_renderer.py:192](mcs/core/context_renderer.py:192) / [:212](mcs/core/context_renderer.py:212)），本变更 MUST 给它们**同时增 `extensions` 与 `purpose` 两参**，否则按 purpose 切换可见性实现不出来；`render_facts`（已有 `purpose`，[:136](mcs/core/context_renderer.py:136)）透传给边渲染。
- **澄清"边渲染 == 边估算"的定位（不是守门铁律一）**：守门器（fanout 预算检查）只渲染**节点层级视图**、**不估算任何关系边**——`tb.estimate(renderer.render([node, *neighbors], "decide_hub"))`（[fanout_reducer.py:395](mcs/plugins/maintenance/fanout_reducer.py:395)），符合宪法"守门只看出边侧层级、不含事实 token"。`estimate_active_view / estimate_fact_edge / estimate_assoc_edge` 在 `mcs/` 内**当前零调用方**。故**边扩展与守门铁律一无关，本变更不触碰守门**。"边渲染 == 估算"属**查询侧 token 计数正确性**：`estimate_*_edge` 已委托 `render_*_edge`（[token_budget.py:106](mcs/core/token_budget.py:106) / [:120](mcs/core/token_budget.py:120)），当 Phase 2 对查询视图按 priority 截断时凭此委托保持一致；Phase 1 查询不截断，可见边字段只影响"给 LLM 看到什么"。
- **派生优先级（仅引入 seam，Phase 1 不接线）**：`priority` 定义为派生值（扩展字段经打分器算）、非写入方权威原语。本期只新增 `PriorityScorer` 接口 + 默认实现（返回 `0.0`，零行为变化）+ "priority 非权威"声明。**不改写路径**——写路径本就不传 priority（全仓无非零 priority 赋值，唯一来源是 store 层 `Edge` 默认 `0.0`）；真实 chokepoint 落 **store 层 `Edge` 创建处**，接线与真实打分逻辑留 Phase 2。
- **库出处记录 + 附加列补齐**：库存 `relation_model` + `schema_version`（+ 扩展集，仅作告警依据）。开库校验：**`relation_model` 不一致 MUST 拒绝**；扩展集变化只**告警**（opt-in 读插件本就时挂时不挂、附加扩展是合法迁移，硬拒会误杀）。**且开库 MUST 补齐附加列**——旧库 `edges` 表无 `extensions_json`，而 `CREATE TABLE IF NOT EXISTS` 对既存表是 no-op、不加列（[sqlite_store.py:571](mcs/stores/sqlite_store.py:571)）；若仅"补 meta 放行"，会放行一个"一写就崩"的库（INSERT 含 `extensions_json` 抛 `OperationalError`，[:494](mcs/stores/sqlite_store.py:494)）。故开库 MUST 检测并 `ALTER TABLE edges ADD COLUMN extensions_json`（附加列、O(1)、安全）。
- **核心算法行为不动**：核心语义定制走既有 prompt 覆盖（A 方案）；不暴露 `in_fanout` / `is_skeleton` 等不变量旋钮。

**OUT OF SCOPE（明确不做）**：

- MCP server 适配层本体（ingest/query 包成工具、协议管道）。
- **配置文件加载**（YAML/JSON → `MCSConfig`）与**插件自动发现**（entry points / 插件目录）——架构已留缝（按名引用 + `MCSBuilder.get_plugin_class` 单一解析点），真打包时再做。
- **注册全新 LLM purpose**——仅当用户加"带自有 LLM 步骤的插件"时才需要，与插件绑定。
- **阶段 2 真实遗忘 / 衰减 / 活跃打分逻辑、派生优先级的写路径接线**——本期仅引入 seam + 默认 no-op。
- **新结构角色 / 用户可改核心图行为（B 方案）**——明确否决。
- **节点侧 `priority`**；**已有库的数据 / `relation_model` 迁移**（**不含** `extensions_json` **附加列补齐**——那是让旧库可写的最小必要，已在 What Changes 内）。
- **守门 / 铁律一不修改**——边与守门估算无关（见上）。

## Capabilities

### New Capabilities

- `edge-extension-model`：边的可扩展字段模型（`EdgeExtensionInterface` + `Edge.extensions` + 存储 / 反查 / 重组保真），与节点对称；字段级渲染可见性（`render(edge, purpose)`，`None`=隐藏）；派生优先级 seam（`PriorityScorer`，Phase 1 默认 `0.0` no-op）。
- `store-provenance`：存储库记录建库出处（`relation_model` + schema 版本 + 扩展集）；开库 `relation_model` 不一致拒绝、扩展集变化告警；旧库附加列（`extensions_json`）补齐，确保放行后可写。

### Modified Capabilities

- `plugin-protocol`：新增 `PluginType.EDGE_EXTENSION` 与 `EdgeExtensionInterface`（`render(edge, purpose)`）；明确字段级可见性契约 = **同一判定规则**（`render(..., purpose)→None` = 隐藏、不渲染）。**不主张"点 / 边在估算侧都计入可见扩展"**——节点扩展在守门估算中本就不计（`estimate_node(extensions=None)`，[token_budget.py:73](mcs/core/token_budget.py:73)），本变更不改此现状。
- `store-interface`：边扩展的存取 / 反查 / 快照 / 重组**保真编解码**；附加列补齐；provenance 元信息读写与开库校验。
- `entities-package`：`Edge` dataclass 增 `extensions` 字段。

## Impact

- **核心模型** (`mcs/entities/graph.py`)：`Edge` 增 `extensions: dict`；`priority` docstring 注记为派生值。
- **接口** (`mcs/interfaces/edge_extension.py` 新增)：`EdgeExtensionInterface`。
- **插件类型** (`mcs/core/plugin.py`)：`PluginType` 增 `EDGE_EXTENSION`。
- **渲染** (`mcs/core/context_renderer.py`)：`render_fact_edge` / `render_assoc_edge` 增 `extensions` + `purpose` 参；`render_facts` 透传 purpose 与边扩展。
- **估算** (`mcs/core/token_budget.py`)：`estimate_fact_edge` / `estimate_assoc_edge` 随渲染签名增 `extensions` + `purpose`（仍委托渲染、保持查询侧一致；当前无调用方，为 Phase 2 截断预留）。**守门 `estimate_node` 不改**。
- **存储** (`mcs/core/store.py`、`mcs/stores/in_memory.py`、`mcs/stores/sqlite_store.py`)：`edges.extensions_json` 列 + 编解码 + 反查 / 快照保真（快照对边 MUST 深拷 `extensions` dict）；开库补 `extensions_json` 附加列；provenance 元表读写与校验。
- **守门 / 重组** (`mcs/plugins/maintenance/fanout_reducer.py`)：`_migrate_edges` 复制边时 MUST 带 `extensions`（保真）；守门口径不变。
- **优先级** (新增 `PriorityScorer` 接口 + 默认实现)：本期仅 seam + 默认 `0.0`；不接写路径。
- **预设 / builder** (`mcs/presets/*`、`mcs/core/builder.py`)：注册边扩展 / 默认 scorer；建库写 provenance、开库校验 + 补列。
- **宪法** (`CLAUDE.md`)：「边方向」注记边 / 点 extensions 对称、`priority` 为派生；**不动铁律一 / 守门口径**（评审后落）。
- **文档** (`docs/architecture.md`)：扩展模型点 / 边对称、字段可见性、派生优先级、provenance。
- **测试** (`tests/`)：边扩展存取 / 反查 / 重组 / 快照保真；可见性（`render→None` 零渲染、按 purpose 切换）；派生 scorer 默认 `0.0`；provenance `relation_model` 拒绝 / 扩展集告警 / 旧库补列后可写；**`property_graph` 基线回归逐字不变**。
