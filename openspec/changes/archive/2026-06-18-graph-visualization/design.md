## Context

记忆 agent 应用 `mcs_agent`（`python -m mcs_agent` 启动）现状：

- `app.py::create_app(agent)` 构建 FastAPI，已有 `POST /chat`、`GET /health`，静态前端 `static/` 挂在 `/`；`app.state.agent` 持有 `MemoryAgent`，其 `.memory` 为 `MemoryStore`。
- `MemoryStore` 以单 worker 线程（`ThreadPoolExecutor(max_workers=1)`）包装 MCS，暴露 5 个导航原语（learn / search / associate / find_path / recall），返回 **LLM 可读文本**。**铁律：所有 MCS 调用必经 `_submit()` 串行执行；FastAPI 路由线程不得直接触碰 `agent.memory._mcs.store`**（MCS 非线程安全 + SQLite 线程亲和）。
- 图只读访问能力齐全（`mcs/core/store.py::StoreInterface`）：`get_node(id)` / `get_out_hierarchy(id)`（层级子节点，驱动下钻）/ `get_facts(id)`（property_graph 事实边，双向可达）/ `get_assoc(id)`（attribute_node 关联边）/ `get_all_nodes` / `get_all_edges`。`relation_model` 取自 `mcs.query_engine.relation_model`（`property_graph` | `attribute_node`）。虚拟根 `__seed_root__`（role=hub，content 空）。
- **关键事实**：`get_facts(id)` / `get_assoc(id)` 返回的是**边**，其另一端节点（property_graph 的邻居概念、attribute_node 的属性节点 `role=attribute`）**不在** `get_out_hierarchy(id)` 的层级子节点中。故关系边的端点节点必须由后端单独收集返回，否则前端无法连线（"边引用不存在节点"）。
- 前端 `static/index.html`：纯 vanilla JS/CSS，**零运行时外部依赖、无构建步骤**。

**当前缺口**：无任何图数据 JSON 端点、无可视化界面；图谱只能经 agent 对话间接访问。

## Goals / Non-Goals

**Goals:**

- 提供只读可视化界面：默认渲染虚拟根 `__seed_root__` 的子图，点节点下钻增量扩展。
- 后端线程安全（经 `_submit` 单 worker 线程）、`relation_model` 感知（关系边来源随模式切换）、返回 JSON 友好的纯 dict。
- **关系边的端点节点随响应一并返回**（在邻居节点集中），前端可立即连线；后端作为节点/边的唯一权威，前端只渲染不自造边。
- 最小改动：不碰 `mcs` 核心包、写路径、`/chat`、`/health`；不触发裂变 / 归纳 / 守门。

**Non-Goals:**

- 不做图的写入 / 编辑 / 删除 / 重挂边（纯只读）。
- 不复用 LLM 渲染口径（铁律一仅约束 LLM 上下文 token 口径；本特性是**人面视图**，与之无关）。
- 不持久化视图状态 / 不做图谱编辑器。
- 不离线本地化 Cytoscape（CDN 即可，离线本地化为后续按需）。
- 不做节点搜索 / 高亮 / 全量图导出 / 路径高亮（v1 范围外，后续）。
- 不为关系边做 priority 截断（Phase 2 派生值未启用，v1 不截断）。

## Decisions

> **数据结构契约**（所有文件一致）：`graph_view(node_id) -> dict | None` 返回
> ```
> { node: {id,name,content,role},                      # 焦点节点
>   nodes: [{id,name,content,role}, ...],              # 邻居：层级子节点 ∪ 关系边端点节点，按 id 去重，不含焦点
>   edges: [{id,source,target,kind,label}, ...],       # hierarchy(焦点→各层级子) ∪ 关系边(fact/assoc)；id 取 edge.id 供前端去重
>   relation_model: "property_graph" | "attribute_node" }
> ```
> 节点不存在时整体返回 `None`。

1. **`MemoryStore.graph_view(node_id)` 只读原语（经 `_submit`），而非路由线程直读 store**
   理由：线程安全铁律——所有 MCS 读必须经单 worker 线程；复用现有 `_submit` 与原语同约束。路由线程直接 `agent.memory._mcs.store.get_*()` 会破坏线程亲和，**否决**。

2. **单端点 `GET /graph/expand?node_id=X`（缺省 `__seed_root__`），初始加载与下钻共用**
   理由：前端逻辑统一（每次都"取某节点邻域、增量并入图"），后端单一入口最简。替代 `/graph/root` + `/graph/expand/{id}` 双端点会重复逻辑，**否决**。

3. **返回 `{node, nodes, edges, relation_model}`：`nodes` = 层级子节点 ∪ 关系边端点节点；`edges` = hierarchy 边 ∪ 关系边**
   理由：见 Context 关键事实——关系边端点不在层级子节点中，必须单独收集进 `nodes` 才能连线；hierarchy 边一并由后端给出，使**后端成为节点/边的唯一权威**，前端只做 add + 渲染，不自造边、不猜结构。`nodes` 按 id 去重（某节点既层级子又关系端点时只一份）。`edges` 关系边按 `relation_model` 取 `get_facts` / `get_assoc`。

4. **模块级纯函数 `_node_to_dict(node) -> {id,name,content,role}` / `_edge_to_dict(edge) -> {id,source,target,kind,label}` 序列化**
   理由：JSON 友好、不泄露 dataclass 内部、与现有 `_render_nodes`（面向 LLM 文本）不同本面向 JSON。`_edge_to_dict` 把 `edge.source_id/target_id` 映射为 `source/target`，`id` 取 `edge.id`（uuid）——供前端按 id 去重并直接作 Cytoscape edge id（避免随机 id 导致同一条边重复并入）。

5. **关系边端点节点 + hierarchy 边由后端统一返回（前端不暂存、不造边）**
   理由：若只返回边不返回端点节点（初稿方案），前端拿到 `edge.target` 但该节点不在图中 → Cytoscape 无法画边；"端点不在则暂存"会让关系边绝大多数时候不显示，与"层级子节点 + 关系边"承诺矛盾。改为端点节点随响应返回后，关系边可立即连线。hierarchy 边同理由后端给（`{source:焦点.id, target:子.id, kind:"hierarchy", label:""}`），前端不必为每个子节点硬造边。

6. **前端 Cytoscape.js（CDN 加载）**
   理由：用户选定；功能丰富（力导向布局、平移缩放、样式）、交互完善、前端代码量最少。代价：引入本项目首个前端运行时依赖 + 需运行时联网（见 Risks）。

7. **增量并入（不重置布局）**
   点节点 → fetch 该节点邻域 → `cy.add(nodes/edges)`（按 id 去重），布局增量运行。`nodes` 与 `edges` 均空的节点标为叶子样式（不可再展开）。

8. **优雅降级：agent 无 `memory` / `graph_view` 时端点返回 503**
   理由：`create_app` 接受任意带 `chat` 的 agent（测试注入裸 fake）。图谱端点用 `getattr` 探测，缺失则 **503**，**不破坏**现有 `/chat` 注入测试。

9. **不预计算 `has_children`（避免 N+1 store 调用）**
   理由：为每个子节点算 `get_out_hierarchy` 非空需 N 次额外 store 调用。v1 选择：点叶子返回空 `nodes`/`edges`，**前端在首次点击后据此判定叶子并缓存状态**——叶子判定发生在请求之后，故首次点击叶子会发一次请求；缓存后该节点后续点击不再重复请求。expand-indicator（预标可展开、免首次请求）列为后续可选优化。

10. **关系边不截断（v1）**
    Phase 2 `priority` 派生值未启用；核心不变量保证根层级子节点有界。深节点可能 children / 关系端点偏多，v1 接受，后续可加 `limit` + 分页兜底。

11. **`role="attribute"` 节点不可下钻**
    理由：attribute_node 模式下属性节点（`role=attribute`）是关系语义的承载端点，不在层级骨架、无层级子节点、不参与 fanout 收敛（见 CLAUDE.md）。前端据 `role` 判定：attribute 节点不响应下钻点击（仅作关系端点显示）；其余节点点击即 fetch。

## Risks / Trade-offs

- **[CDN 依赖 + 运行时联网]** → 离线环境图谱页加载空白。缓解：用固定版本 CDN URL（避免隐式升级）；后续可把 `cytoscape.min.js` 本地化到 `static/`（非本次范围）。
- **[首个前端运行时依赖]** → 引入版本锁定与供应链面。缓解：固定版本号、CDN 选主流可信源。
- **[深节点大扇出]** → v1 不限 children / 关系端点 / 关系边数量，靠核心不变量（根层级 ≤ T）兜底；深节点可能渲染较多元素（`nodes` 含关系端点后更多）。缓解：后续加 `limit` + "展开更多"。
- **[graph_view 序列化口径 ≠ LLM 渲染口径]** → 有意为之（人面视图）。须在代码注释与 spec 注明，避免被误判为违反铁律一。
- **[attribute_node 模式 assoc 边无 label]** → 前端渲染为无 label 连线，与 property_graph fact 边（带 label）视觉区分（不同样式）。
- ~~关系边端点不在视图~~ → **已解决**（决策 5：端点节点随响应返回）。

## Migration Plan

- 纯新增，无数据迁移、无存储 schema 变更、不改现有端点与原语语义。
- **回滚**：删 `static/graph.html`、删 `app.py` 的 `/graph/expand` 端点、删 `memory.py` 的 `graph_view` 与序列化函数、删 `index.html` 导航链接。回滚不影响 `/chat`、`/health` 与 5 工具。

## Open Questions

- 是否需要节点搜索 / 高亮 / 全量导出 / 路径高亮？（v1 否；按后续使用反馈再定）
- Cytoscape 是否需本地化以支持离线部署？（按部署环境后续决定）
- 是否需要 expand-indicator（预标可展开节点）？（v1 以"点后空即叶子"替代；可选后续）
- `__seed_root__` 显示名美化？（name 即 id，前端原样显示略生硬；可在前端给别名如"根 / 全部记忆"，按审美后续定）
