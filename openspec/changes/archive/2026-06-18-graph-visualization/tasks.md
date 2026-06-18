# Implementation Tasks

> 编码规范：所有 import 集中到文件顶部（项目宪法）。最小改动原则：不碰 `mcs` 核心、写路径、`/chat`、`/health`、5 工具。运行环境用根目录 `.venv`，测试 `.venv\Scripts\python.exe -m pytest -q`。
>
> **数据结构契约**（design/spec 一致）：`graph_view` 返回 `{node, nodes(层级子∪关系端点,去重), edges(hierarchy 边 焦点→子 ∪ 关系边, 每条含 id), relation_model}`，节点不存在返回 `None`。

## 1. 后端：MemoryStore graph_view 只读原语

- [x] 1.1 在 `mcs_agent/memory.py` 顶部 import 区确认 `Node`/`Edge` 已引入；新增模块级纯函数 `_node_to_dict(node) -> {id,name,content,role}` 与 `_edge_to_dict(edge) -> {id,source,target,kind,label}`（`id` 取 `edge.id` 供前端去重；`source/target` 由 `edge.source_id/target_id` 映射）
- [x] 1.2 新增 `MemoryStore._do_graph_view(node_id) -> dict | None`（worker 线程内）：`get_node`（不存在→`None`）；`get_out_hierarchy` 取层级子节点；按 `mcs.query_engine.relation_model` 取 `get_facts`/`get_assoc` 关系边；**收集关系边的另一端节点**（`get_node(edge 的另一端 id)`）；组装 `nodes = 层级子 ∪ 关系端点`（按 id 去重、不含焦点）、`edges = [hierarchy 边 焦点→各子] ∪ 关系边`、`relation_model`；返回 `{node, nodes, edges, relation_model}`。再加 `graph_view(node_id) -> dict | None`（经 `_submit` 转发）
- [x] 1.3 处理边界：节点不存在返回 `None`（不抛异常）；孤立叶子 → `nodes=[]`、`edges=[]`；`role="attribute"` 节点照常序列化进 `nodes`；关系边另一端 `get_node` 返回 `None`（悬空边）时跳过该端点不崩、该边仍保留进 `edges`

## 2. 后端测试：graph_view 原语

- [x] 2.1 新增 `tests/test_graph_view.py`。构造 fake mcs（MUST 暴露 `.query_engine.relation_model` 与 `.store` 的 `get_node/get_out_hierarchy/get_facts/get_assoc`），用真实 `MemoryStore(lambda: fake_mcs)` 测：根视图（`node.id=="__seed_root__"` + `nodes` + `edges` + `relation_model`）、节点不存在→`None`、孤立叶子→`nodes==[]` 且 `edges==[]`
- [x] 2.2 测 `relation_model=="property_graph"`：`edges` 中 `kind=="fact"` 边来自 `get_facts`、`label` 非空，且每条 fact 边另一端节点出现在 `nodes` 中
- [x] 2.3 构造 `relation_model=="attribute_node"` 的 fake mcs：`edges` 中 `kind=="assoc"` 边来自 `get_assoc`、`label` 为空，且关联端点（`role=="attribute"`）出现在 `nodes` 中
- [x] 2.4 测返回结构为 JSON 友好纯 dict：`node`/`nodes[*]` 恰为 `{id,name,content,role}`、`edges[*]` 恰为 `{id,source,target,kind,label}` 且 `kind∈{hierarchy,fact,assoc}`、顶层含 `relation_model`；`nodes` 按 id 去重（重叠节点只一份）；hierarchy 边 `source==焦点.id && kind=="hierarchy" && label==""`
- [x] 2.5 测线程安全：fake mcs 的读方法记录执行线程 id，断言与调用方（测试主线程）不同（经 `_submit` 单 worker 线程）

## 3. 后端：GET /graph/expand 端点

- [x] 3.1 在 `mcs_agent/app.py::create_app` 加只读端点 `GET /graph/expand?node_id=__seed_root__`（`node_id` 缺省根）；用 `getattr` 探测 `agent.memory` 与 `memory.graph_view`，缺失时返回 **503** 优雅降级
- [x] 3.2 `graph_view` 返回 `None` → **404**；正常 → 返回 dict（FastAPI 自动转 JSON）

## 4. 后端测试：端点

- [x] 4.1 用 `TestClient` + 注入暴露 `graph_view` 的 fake memory/agent，测缺省根→200（`node.id=="__seed_root__"`）、指定存在 id→200、不存在 id→404
- [x] 4.2 注入无 `memory` 的裸 fake agent（仅 `chat`），测 `GET /graph/expand`→**503** 优雅降级，且同 app `/chat` 仍转发到 `fake_agent.chat` 不被破坏

## 5. 前端：graph.html 可视化页

- [x] 5.1 新增 `mcs_agent/static/graph.html`：CDN 引入 Cytoscape.js（**固定版本号** URL），布局容器 + 节点详情面板（name/content/role）+ 头部导航链接回 `/`（聊天）
- [x] 5.2 打开即默认 `GET /graph/expand`（缺省根）渲染 `__seed_root__` 及返回的 `nodes`/`edges`；样式按 role 区分（root / hub / concept / attribute）、边按 kind 区分（hierarchy 实线 / fact 带 label / assoc 无 label）。**前端只渲染后端返回的 edges，不自造边**
- [x] 5.3 `tap` 节点：`role=="attribute"` 不响应下钻（仅作关系端点）；其余节点 → `GET /graph/expand?node_id=<id>` 增量并入返回的 `nodes`/`edges`（按 id 去重）；**返回空的节点标叶子样式并缓存该状态，后续点击不重复请求**
- [x] 5.4 关系边按 `relation_model` 渲染：`property_graph` 事实边带 label、`attribute_node` 关联边无 label（边样式区分）
- [x] 5.5 `static/index.html` 头部加一行导航链接到 `/graph.html`（最小改动，不动聊天逻辑）

## 6. 验收与收尾

- [x] 6.1 跑全量测试 `.venv\Scripts\python.exe -m pytest -q`，确保默认基线行为不变（无回归）
- [ ] 6.2 手动启动 `python -m mcs_agent` 验收：默认根子图渲染、点非叶子/非 attribute 节点下钻并入、关系边及其端点节点可见、重复点去重、叶子与 attribute 不可展开、两模式边渲染正确（**留用户本地环境验收**：需真实 `MCS_CONFIG` + `AGENT_LLM_API_KEY`；已用真实 `MemoryStore`+fake mcs 经端点 + 静态页端到端冒烟验证 200）
- [x] 6.3 确认 `/chat`、`/health`、5 导航工具行为逐字不变；可视化纯只读、不触发 ingest / 守门 / 裂变（全量 608 passed 含 agent 三套测试；新原语只读、未触写管线）
