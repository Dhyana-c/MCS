## Why

记忆图谱（MCS）目前只能经记忆 agent 的对话间接访问，无法直观查看图结构与层级组织。需要一个**只读可视化界面**：默认展示虚拟根 `__seed_root__` 的子图，支持点节点下钻扩展，让人能直接审视知识组织（hub 层级、概念归属、关系边），辅助调试、验收与对图谱质量的直观判断。

## What Changes

- **后端只读原语**：`MemoryStore.graph_view(node_id)`——在单 worker 线程内返回**焦点节点 + 邻居节点集**（层级子节点 `get_out_hierarchy` ∪ 关系边端点节点）**+ 边集**（hierarchy 边 `焦点→子` ∪ 关系边，按 `relation_model` 取 `get_facts` / `get_assoc`）+ 当前 `relation_model`，序列化为纯 dict（JSON 友好），不在路由线程触碰 MCS。**关系边的另一端节点随响应一并返回**（在邻居集里），前端可立即连线，不会出现"边引用不存在节点"。
- **后端只读端点**：`GET /graph/expand?node_id=__seed_root__`（缺省虚拟根），转发到 `graph_view`；节点不存在 → 404。
- **前端可视化页**：新增独立页 `static/graph.html`（Cytoscape.js，CDN 加载）——默认拉根子图，点节点调同一端点增量并入图（按 id 去重、空子节点标为叶子），节点详情面板显示 name/content/role。
- **前端导航**：`static/index.html` 头部加导航链接到图谱页。
- **不改**：`/chat`、`/health`、写入路径、`mcs` 核心包；不触发裂变 / 归纳 / 守门；不破坏核心不变量（这是**人面只读视图**，不复用 LLM 渲染口径，铁律一与其无关）。

## Capabilities

### New Capabilities

- `graph-visualization`: 记忆图谱只读可视化能力——涵盖 `MemoryStore.graph_view` 只读原语（worker 线程执行、`relation_model` 感知）、`GET /graph/expand` JSON 端点、`graph.html` 默认渲染根子图 + 点击下钻交互。

### Modified Capabilities

<!-- 无：本变更不改变 memory-agent 现有任何 requirement 的语义（现有 /chat、/health、5 工具、MemoryStore 原语行为逐字不变）；新增端点与原语属于 graph-visualization 新能力。 -->

（无）

## Impact

- **代码**：`mcs_agent/memory.py`（+`graph_view` + 序列化纯函数）、`mcs_agent/app.py`（+`/graph/expand` 端点）、`mcs_agent/static/graph.html`（新文件）、`mcs_agent/static/index.html`（+1 行导航链接）。
- **依赖**：引入本项目**首个前端运行时依赖** Cytoscape.js（经 CDN，需运行时联网；离线本地化为后续非本次范围）。
- **测试**：新增 `graph_view`（根视图 / 节点不存在 / 叶子空 / property_graph 取 facts 带 label / attribute_node 取 assoc 无 label / attribute role 序列化）与 `/graph/expand` 端点（缺省根 → 200、不存在 → 404、注入无 memory 的 fake → 优雅降级）测试。
- **不变量 / 铁律**：只读、人面视图，不进写入 / 守门 / 裂变路径，不影响核心不变量；可视化不复用 LLM 渲染口径（铁律一仅约束 LLM 上下文 token 口径）。
- **线程安全**：新原语必经 `MemoryStore._submit`（单 worker 线程），与现有原语同约束，FastAPI 路由线程不直接触碰 MCS / store。
