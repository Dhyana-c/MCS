# Implementation Tasks

## 0. core 守门入口（路径 B，前置）

- [x] 0.1 `mcs/core/write_pipeline.py`：新增 public `run_compaction(changed_nodes: list[Node]) -> None`，一行转发 `self._run_compaction(changed_nodes)`。不改 `_run_compaction` 内部逻辑（ingest 阶段⑥仍调它）。
- [x] 0.2 `mcs/core/mcs.py`：新增 public `run_compaction(changed_nodes)`，转发 `self.write_pipeline.run_compaction(changed_nodes)`。
- [x] 0.3 测试 core 守门入口：`MCS.run_compaction(changed)` / `WritePipeline.run_compaction(changed)` 等价于阶段⑥（超 T 强制裂变、无 CompactionPlugin 时 `logger.error`）；ingest 既有守门行为不变。

## 1. Prompts

- [x] 1.1 新增 `mcs/prompts/split.py`：`SYSTEM_PROMPT` / `USER_TEMPLATE` / `parse`。要点——判定节点是否耦合多个语义中心；两类（类别-特化 `is_a` / 多实体误并 `none`）；**必须为每条原边指定归属**；跨两产物关系的边 → 产 `role=fact` 节点承接；未耦合返回 `action=noop`。`parse` 只做结构校验（`into` 非空）；原边全覆盖校验+漏边降级在 `_do_split` 执行侧做（parse 无原边集上下文）。含两类 few-shot（按摩型 / 小明小红型）。
- [x] 1.2 新增 `mcs/prompts/merge.py`：同骨架。判定是否同义 / 重复；产出 `keep` / `absorb` / `merged_content` / `aliases_to_add`；**互斥对禁合**返回 `noop` 并说明；非同义 `noop`。`parse` 校验 `keep` / `absorb` 均在传入 id 集合内、`keep` 不在 `absorb` 中。**不复用 `judge_relations`**（口径不同）。
- [x] 1.3 `mcs/prompts/__init__.py`：import `split` / `merge` 并注册进 `DEFAULT_PROMPTS`（仿 `generalize` / `adjudicate`）。

## 2. MemoryStore 原语（`mcs_agent/memory.py`）

- [x] 2.1 `split_concept(node_id, focus=None) -> str`：`_submit(self._do_split, ...)`。`_do_split` = 取节点（不存在返回提示）→ `get_relations` 取关联/互斥 + `get_related_events` 取事件背书 → 自建 material（content + 原边含对端 name，**不截断**——T 非 LLM 单次 context 约束，截断丢边破坏边全覆盖校验）→ `split` purpose 调 LLM → `parse` 校验 → `store.snapshot()` → 建产物 / 按归属迁边 / 事件背书边自动迁 `parent` / 连产物间 `关联` / 删原节点 → 失败 `restore` → `self._mcs.run_compaction(产物节点)` 过守门 → 渲染返回（含产物 id）。
- [x] 2.2 `merge_concepts(node_ids, focus=None) -> str`：`_submit(self._do_merge, ...)`。`_do_merge` = 取节点（不存在跳过、全空返回提示）→ 自建 material → `merge` purpose → **互斥安全闸**（扫 `keep`↔`absorb` 互斥边，命中拒绝）→ `parse` 校验 → `snapshot` → absorb 边迁向 `keep`（`add_edge` 去重）/ `aliases` 并入 `keep` / 删 absorb → 失败 `restore` → `self._mcs.run_compaction(keep 节点)` 过守门（可能触发 `decide_hub` 裂变，由守门兜）→ 渲染返回。
- [x] 2.3 漏边降级：`split` 执行前比对原边集与 `edges` 覆盖集，漏指的边透明挂 `parent`（无 parent 则首个非 fact 产物）+ 返回文本列出"暂挂"提示。

## 3. 工具注册（`mcs_agent/tools.py` / `loop.py`）

- [x] 3.1 `BUILTIN_TOOLS` 加 `split` / `merge` 两 `ToolSpec`（`readonly=False`，handler `_split` / `_merge` 调 `memory.split_concept` / `merge_concepts`）；schema 含触发红线描述（何时不该调）。
- [x] 3.2 `loop.py` `DEFAULT_SYSTEM_PROMPT` 补两工具说明（含"何时不该调"红线：content 自洽别拆、同名异义别合、互斥禁合）。
- [x] 3.3 `MEMORY_TOOLS` 废弃别名随之含 9；`READONLY_TOOL_NAMES` 自动排除两新写图工具（由 `readonly=False` 驱动，不需手改白名单）。

## 4. 测试（含边界，`.venv\Scripts\python.exe -m pytest -q`）

- [x] 4.1 `split` 两类：类别-特化（按摩 `is_a`，产物间连 `关联`）/ 多实体误并（小明小红 `none`，平级）。
- [x] 4.2 `split` `noop`：专用 prompt 复核判未耦合 → 不改图。
- [x] 4.3 `split` 漏边：`edges` 未全覆盖 → 执行侧漏边降级（透明挂 `parent`）+ 返回文本提示"暂挂"。
- [x] 4.4 `split` 跨关系边物化 `role=fact` 产物承接（谓词落 content、连两端）。
- [x] 4.5 `split` 原子回滚：执行中失败 → `restore` → 图无残留（无半拆分节点、无悬空边）。
- [x] 4.6 `split` 事件背书边自动迁 `parent`（不交 LLM、不随 `delete_node` 丢失）。
- [x] 4.7 `merge` 同义合并 + `aliases` 收口（absorb 的 name/aliases 并入 keep）。
- [x] 4.8 `merge` 互斥禁合：prompt `noop` + 机制层保险双闸。
- [x] 4.9 `merge` 增扇出守门：合并后超 T → 过守门（验证不抛、由守门兜）。
- [x] 4.10 `merge` 原子回滚。
- [x] 4.11 `split` / `merge` `readonly=False`：不在 `READONLY_TOOL_NAMES`、不进 `/recall` 白名单。
- [x] 4.12 `split` / `merge` 节点不存在 / 空入参：返回提示文本、不抛、不改图、不调 LLM。
- [x] 4.13 现有 mock 工具集（`test_agent_tools` / `test_agent_loop` / `test_agent_trace` 等）补齐两新工具的调度 mock，避免"未知工具"误报。

## 5. 文档（保证代码与文档统一）

- [x] 5.1 `docs/graph-model-design.md` 补「概念拆分 / 合并（agent 工具层）」段——区别于 core 聚类重组（split 是节点**自身**分裂、波及关系边；聚类 fanout 只动组织层级、不波及关系边）。
- [x] 5.2 `docs/memory-agent.md` 工具表加 `split` / `merge` 两行、7→9、补触发红线说明。
- [x] 5.3 `mcs_agent/tools.py` 模块 docstring 工具数 7→9。

## 6. 验收

- [x] 6.1 `openspec validate agent-split-merge --strict` 通过。
- [x] 6.2 `.venv\Scripts\python.exe -m pytest -q` 全绿。
