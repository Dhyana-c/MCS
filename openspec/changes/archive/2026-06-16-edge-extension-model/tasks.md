## 1. 接口与插件类型（D1）

- [x] 1.1 `PluginType` 增 `EDGE_EXTENSION = "edge_extension"`（`mcs/core/plugin.py`）
- [x] 1.2 新增 `mcs/interfaces/edge_extension.py`：`EdgeExtensionInterface(Plugin)`，镜像 `NodeExtensionInterface`——`get_type()→EDGE_EXTENSION`、抽象 `schema() / default() / serialize() / deserialize()`、可选 `render(edge, purpose) -> str | None`（默认 `None`）、`execute()` 抛 `NotImplementedError`
- [x] 1.3 `mcs/interfaces/__init__.py` 导出 `EdgeExtensionInterface`

## 2. 核心模型与存储——边扩展槽（D2）

- [x] 2.1 `Edge` 增 `extensions: dict[str, Any] = field(default_factory=dict)`；更新 docstring（`mcs/entities/graph.py`）
- [x] 2.2 `store.add_edge` 增 `extensions: dict | None = None` 参，落到 `Edge.extensions`（`mcs/core/store.py`、`mcs/stores/in_memory.py`、`mcs/stores/sqlite_store.py`）
- [x] 2.3 `SQLiteStore`：`edges` 表增 `extensions_json TEXT` 列；持有 `_edge_extensions`（name→插件）保真编解码，复用 `nodes` 的 `extensions_json` 路径；`save_full` / `load` 逐条保真（`mcs/stores/sqlite_store.py`）
- [x] 2.4 `InMemoryStore`：`Edge.extensions` 随对象存取，无需编解码（`mcs/stores/in_memory.py`）
- [x] 2.5 **快照深拷**：`snapshot` 对边由 `dc_replace(e)` 改为 `dc_replace(e, extensions=dict(e.extensions or {}))`（与节点一致，防引用共享）；两 store 都改（`mcs/stores/in_memory.py:293`、`mcs/stores/sqlite_store.py:343`）；`restore` 覆盖边 `extensions`
- [x] 2.6 反查保真验证：`get_facts` / `get_assoc` 两端返回的边对象 `extensions` 完整（验证，非新增逻辑）
- [x] 2.7 `builder` 把 `EDGE_EXTENSION` 插件以 name→插件传给 store（与 `node_extensions` 对称）（`mcs/core/builder.py`、`mcs/stores/sqlite_store.py` 的 `initialize`）
- [x] 2.8 **不动** `StorageSchemaExtensionInterface`（不加 `edge_columns()`——本期 json 单列足够，加抽象方法会破坏既有实现）

## 3. 渲染——字段可见性 + purpose 参（D3，review C）

- [x] 3.1 `render_fact_edge` / `render_assoc_edge` **同时增 `extensions` 与 `purpose` 两参**（`purpose` 带安全默认 `"select_facts"`、`extensions` 默认 `None`，使既存内部调用不破签名）；可见片段（`ext.render(edge, purpose)` 非 `None`）追加到边渲染文本（`mcs/core/context_renderer.py`）
- [x] 3.2 `render_facts` 取 `get_all(EDGE_EXTENSION)`、并把自身 `purpose` 透传给边渲染（`mcs/core/context_renderer.py`）
- [x] 3.3 `estimate_fact_edge` / `estimate_assoc_edge` 随渲染签名增 `extensions` + `purpose`（同样带安全默认），仍**委托** `render_*_edge` 后估算（不另开公式）；保持查询侧渲染 == 估算口径。注：当前二者**零调用方**，为 Phase 2 查询视图截断预留正确接缝（`mcs/core/token_budget.py`）
- [x] 3.6 `estimate_active_view`（死代码、零调用方，[token_budget.py:123](mcs/core/token_budget.py:123)）内部 `est_edge(edge, node_map)` 经 `purpose`/`extensions` 安全默认**继续可用**；本期**不删不改**（避免触动可能引用它的 spec/test；Phase 2 接真实截断时再决定显式传参）
- [x] 3.4 **守门不改**：`estimate_node`（`extensions=None`、`purpose="decide_hub"`）与 fanout 守门口径**保持现状**；本变更 MUST NOT 触碰守门 / `subgraph-bounding`
- [x] 3.5 单测锁定：边扩展 `render→None` 时零渲染；返回片段时进渲染；同一边在不同 purpose 下可见性可不同

## 4. 派生优先级——seam，Phase 1 不接线（D4）

- [x] 4.1 新增 `PriorityScorer` 接口 + 默认实现 `score(edge) -> float` 返回 `0.0`（零行为变化）
- [x] 4.2 builder 注入默认 scorer；文档 / docstring 声明"`priority` 派生、非权威，真实来源是扩展字段 + scorer"
- [x] 4.3 **本期不改写路径 / 不在 chokepoint 接 scorer**：Phase 1 无可派生字段（活跃数 / 创建时间属 Phase 2）；真实 chokepoint（store 层 `Edge` 创建）与真实打分留 Phase 2。是否升格 `PluginType.PRIORITY_SCORER` 亦留 Phase 2

## 5. 重组保真（D2 / D4，review D）

- [x] 5.1 `FanoutReducerPlugin._migrate_edges` 重建边时增 `extensions=edge.extensions`（保真复制，否则合并迁移丢扩展）（`mcs/plugins/maintenance/fanout_reducer.py:688`）
- [x] 5.2 `priority` 在重组复制处暂仍按 `edge.priority` 复制（Phase 2 改为经 scorer 重算）；本期不改其行为

## 6. 库出处记录 + 旧库补列（D5，review E + 我方发现）

- [x] 6.1 `SQLiteStore` 建 `meta(key TEXT PRIMARY KEY, value TEXT)` 表；建库写 `relation_model` / `schema_version` / `extensions`（点+边扩展名集，排序序列化）（`mcs/stores/sqlite_store.py`）
- [x] 6.2 **旧库附加列补齐**：开库时 `PRAGMA table_info(edges)` 检测 `extensions_json` 是否存在，缺则 `ALTER TABLE edges ADD COLUMN extensions_json TEXT`（`mcs/stores/sqlite_store.py` 的 `initialize` / `_create_tables` 后）
- [x] 6.3 开库三态校验：`relation_model` 不一致→抛配置类错误**拒绝**；`extensions` 集变化→**仅 WARNING 放行**；`meta` 缺失（旧库）→按当前配置补写 + WARNING 放行
- [x] 6.4 校验 + 补列 MUST 先于任何读写（store `initialize` / builder 装配点）；`InMemoryStore` 全程 no-op

## 7. 预设 / builder / 宪法 / 文档

- [x] 7.1 `presets` 暴露注册边扩展、默认 scorer 的入口（与节点扩展对称）；Phase1 默认插件集**不**默认挂边扩展（基线零变化、边扩展 opt-in）（`mcs/presets/*`）
- [x] 7.2 proposal 评审通过后改 `CLAUDE.md`「边方向」：注记边 / 点 `extensions` 对称、`priority` 为派生值；**不动铁律一 / 守门口径**
- [x] 7.3 `docs/architecture.md`：扩展模型点 / 边对称、字段可见性、派生优先级 seam、provenance

## 8. 测试与回归

- [x] 8.1 单测：`Edge(extensions=...)` 存取；SQLite `extensions_json` 编解码保真；`get_facts` / `get_assoc` 反查返回的边 `extensions` 完整
- [x] 8.2 单测：可见性——`render(edge, purpose)` 返回片段则进渲染、返回 `None` 则零渲染；同边不同 purpose 可见性可不同
- [x] 8.3 单测：边渲染 == 估算（`estimate_*_edge` 委托 `render_*_edge`、含可见扩展片段、同 purpose）；**守门 `estimate_node` 行为不变**（回归）
- [x] 8.4 单测：派生 scorer 默认 `score()` 返回 `0.0`；写边后 `priority` 仍为 `0.0`（零行为变化）
- [x] 8.5 单测：重组——`_migrate_edges` 后边 `extensions` 完整保真；快照 / restore 后边 `extensions` 为独立 dict（无引用共享）
- [x] 8.6 单测：provenance——`relation_model` 不一致 MUST 拒绝；扩展集变化仅告警放行；`meta` 缺失补写放行
- [x] 8.7 单测：旧库（无 `extensions_json` 列、无 `meta`）开库后补列 + 补 meta，且**可正常写入**（INSERT 不抛 `OperationalError`）
- [x] 8.8 基线回归：未挂任何边扩展时，写入 / 查询 / 渲染 / 守门 / 重组**逐字不变**；`property_graph` 全仓回归全绿（`.venv\Scripts\python.exe -m pytest -q`）
