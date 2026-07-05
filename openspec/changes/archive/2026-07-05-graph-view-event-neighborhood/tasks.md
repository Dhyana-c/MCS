## 1. graph_view 补事件邻域 + degree（mcs_agent/memory.py）

- [x] 1.1 `_do_graph_view`：用 `store.get_related_events`（绕载重）补事件节点 + `get_edges_between` 取事件→焦点背书边；`nodes` 含相关事件、`edges` 含事件背书边
- [x] 1.2 `_do_graph_view`：`edges` 按 `edge.id` 去重（兜 store 实现差异 / FakeStore 不做载重）
- [x] 1.3 `_degree`：改「不同邻居数」（rel 边端点 ∪ 相关事件，去重），修复旧「下钻+关系」翻倍

## 2. 前端事件可下钻（mcs_mem/static/graph.html）

- [x] 2.1 删 `DRILLABLE` class 预判，`cxttap` 任何节点都可右键下钻（事件 expand 返回其涉及的概念/事实；source/孤立空则标叶子）
- [x] 2.2 hint 文案更新（概念/事实/事件）

## 3. 测试（tests/test_graph_view.py）

- [x] 3.1 FakeStore 加 `get_related_events` + `get_edges_between`
- [x] 3.2 `test_dict_fields` 的 root degree 断言 2→1（统一模型不翻倍）
- [x] 3.3 新增 `test_event_endorsement_visible_in_view`（焦点概念有事件背书 → nodes 含事件、edges 含事件→概念边、degree 含事件邻居）

## 4. spec delta

- [x] 4.1 `specs/graph-visualization/spec.md` delta：MODIFIED 三个 requirement（graph_view 只读原语 / 返回结构 / graph.html 下钻），含事件邻域、degree 邻居去重、事件可下钻、edges 按 id 去重

## 5. 验证

- [x] 5.1 `.venv/Scripts/python.exe -m pytest -q` 全绿（1037 passed）
- [x] 5.2 重启 mcs_mem + curl `/graph/expand?node_id=__seed_root__`：root degree=4（不翻倍）、按摩能看到 2 个背书事件 + 事件边
- [x] 5.3 curl 事件节点 expand：返回其涉及的概念/事实（全图可达）
