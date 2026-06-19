# Tasks: graph-summary

## 1. store-interface 图级 meta 原语

- [x] 1.1 `StoreInterface`（`mcs/core/store.py`）新增抽象方法 `get_graph_meta(key) -> str | None` / `set_graph_meta(key, value) -> None`
- [x] 1.2 `InMemoryStore`（`mcs/stores/in_memory.py`）dict 实现 meta kv
- [x] 1.3 `SQLiteStore`（`mcs/stores/sqlite_store.py`）**复用既有 `meta(key, value)` 表**实现 meta kv（不新建表——实现期细化，复用 provenance 同款 kv 基础设施）
- [x] 1.4 `set_graph_meta` 即时落库 + 跨实例 `load` 保真（复用 meta 表，无需改 save_full）
- [x] 1.5 测试：meta CRUD、round-trip 保真、缺 key 返回 None、set 覆盖（`tests/test_graph_meta.py`，8 passed；全量 619 passed 基线不变）

## 2. graph-summary compaction 插件

- [x] 2.0 在 `mcs/prompts/` 注册 `gen_graph_summary` PromptBundle（`mcs/prompts/gen_graph_summary.py` + `DEFAULT_PROMPTS` 登记）
- [x] 2.1 新建 `mcs/plugins/maintenance/graph_summary.py`，`GraphSummaryPlugin(CompactionPluginInterface)`
- [x] 2.2 `should_run`：判 `changed_nodes` 含 `role="concept"` 新节点
- [x] 2.3 `run`：读顶层 hub → 经 `llm_caller(purpose="gen_graph_summary", ...)` 归纳 ≤ `max_tokens`（默认 1000）→ `set_graph_meta("graph_summary", text)`
- [x] 2.4 归纳异常隔离（try/except + 日志 + 保留旧摘要 + 不阻塞 ingest）
- [x] 2.5 空图降级（root 无层级子 → 提前 return，不抛异常）
- [x] 2.6 注册表（`phase1.py`）加 `graph_summary` + 默认列表 `PHASE1_WRITE_PLUGINS`（`config.py`）加 `graph_summary`（末尾，fanout 后跑）
- [x] 2.7 测试（`tests/test_graph_summary_plugin.py`，9 passed；守护测试 `test_skeleton` 同步更新：插件 9→10、purpose +gen_graph_summary）

## 3. MemoryStore.graph_summary 原语

- [x] 3.1 `MemoryStore.graph_summary() -> str`（worker 线程读 `get_graph_meta("graph_summary")`，无则空串）
- [x] 3.2 测试：取摘要、空图返回空串、经单 worker 线程（`tests/test_agent_memory.py`，+2 用例，17 passed）

## 4. agent 注入摘要 + 路由 prompt

- [x] 4.1 `MemoryAgent.chat()` 每轮取 `memory.graph_summary()` 注入 system「当前记忆图主题」段（`_fetch_summary` + `_build_system`）
- [x] 4.2 喂前摘要 ≤ `summary_budget`（默认 1000）校验 / 截断（第二道闸）
- [x] 4.3 改写 `DEFAULT_SYSTEM_PROMPT`（补「何时直接答」「何时探索」「探索策略」「记忆诚实」「learn 边界」段，保留 5 工具说明 + id 引用）
- [x] 4.4 测试（`tests/test_agent_loop.py` +5）：摘要注入、超标截断、空摘要占位、无 graph_summary 容错、路由 prompt 关键段存在

## 5. spec 同步

- [x] 5.1 新增 `specs/graph-summary/spec.md`（3 requirements，delta 头已修正）
- [x] 5.2 `specs/store-interface/spec.md` delta（图级 meta 原语 + 复用 meta 表持久化）
- [x] 5.3 `specs/memory-agent/spec.md` delta（路由 prompt MODIFIED + 摘要注入 ADDED + graph_summary 原语 ADDED）

## 6. 集成与回归

- [x] 6.1 端到端：`test_ingest_writes_graph_summary_meta`——ingest concept → 阶段⑥调度 GraphSummaryPlugin → 摘要写入 meta（经真实 WritePipeline）
- [x] 6.2 默认基线行为不变：`.venv/Scripts/python.exe -m pytest tests/ -q` **636 passed**（含本 change 新增 20 用例），守护测试 `test_skeleton` 已同步（插件 9→10、purpose +gen_graph_summary）；`openspec validate graph-summary --strict` 通过
