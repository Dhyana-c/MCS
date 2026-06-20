## 1. 宪法先行（先改宪法再改代码）

- [x] 1.1 `CLAUDE.md` 总体流程：补"每次 ingest 整个输入记为一个事件（记录行为，落时间轴）"，明确 source/event 规则建、只 content 走 LLM
- [x] 1.2 `docs/graph-model-design.md` §5.1：去 docs-migration 留的"过渡态"实现现状注，补"每次 ingest = 一个记录事件"，确认 ①④ 描述与本 change 一致

## 2. 数据结构

- [x] 2.1 在 `mcs/entities/` 新增 `IngestInput` 数据类（content / timestamp? / source?: SourceData / event_name? / metadata），并入 `__all__`
- [x] 2.2 `WriteContext` 增字段：本次事件节点 + source 节点列表（不移除既有八个字段）

## 3. 核心：统一 ingest 流程

- [x] 3.1 `WritePipeline.ingest` 入口归一化 `str | IngestInput`（str → `IngestInput(content=text)`，now 时间戳、无 source）
- [x] 3.2 拆 `ingest_event` / `ingest_source` 为「建节点」+「连背书边」两原语；保持 MCP `ingest_event` 工具对外行为逐字等价（建节点 + 按 target_ids 连边）
- [x] 3.3 新增规则入库段 ⓪：建事件节点（整输入，timestamp）+ 按 `source` 规则切分建 source 节点（不经 LLM）；写入 `WriteContext`
- [x] 3.4 ③ 概念提取仅以 `content` 为输入（不再用整 str）
- [x] 3.5 ⑤ 图更新后连背书边：事件 / source → 本次新建 / 命中的概念 / 事实（`关联` 边，事件 / source 为源端）
- [x] 3.6 空 content 路径：保证早返回前事件 / source 已建、且随 ⑦ 落盘
- [x] 3.7 验证载重规则不被新连边破坏（核心节点 `get_relations` 仍过滤事件边）

## 4. 调用方对齐

- [x] 4.1 `mcs_mcp/server.py`：ingest 工具仍传 str（走兼容路径）；确认 ingest_event 工具行为不变
- [x] 4.2 `mcs_agent`（`MemoryStore.learn` / loop）：learn 仍传 str；确认行为不变
- [x] 4.3 `bench/multihop_rag/builder.py`：确认建图路径兼容（如需带 source/doc 出处可改传 `IngestInput`）
- [x] 4.4 `examples/basic_usage.py`、`wiki_example.py`：确认运行无回归

## 5. 测试（覆盖边界）

- [x] 5.1 纯文本 str 入参：恰一个事件（now）+ 概念 / 事实，无 source，行为兼容
- [x] 5.2 `IngestInput` 带 timestamp / source：事件用给定 timestamp；source 按 chunks 切分建多节点
- [x] 5.3 背书连边：事件 / source → 抽出概念 / 事实存在且方向正确
- [x] 5.4 载重规则：`get_relations(概念)` 不含事件边、`get_related_events(概念)` 可达事件
- [x] 5.5 空 content：仍建事件（+ source）、落盘成功、不抛
- [x] 5.6 转述过去事件（"三年前发生 X"）：抽成带时间属性的事实，不成第二个时间轴事件
- [x] 5.7 幂等：重复块跳过概念抽取的语义不破（调用方幂等契约不变）

## 6. 文档回灌（落地后转为已实现）

- [x] 6.1 `docs/api-reference.md`：ingest 入参（str | IngestInput）、ingest_event/source 改为"统一 ingest 内部规则原语 + 低层入口"
- [x] 6.2 `docs/getting-started.md`：去"独立直插原语"过渡注，示例改为结构化 ingest（保留 str 简例）
- [x] 6.3 `docs/architecture.md` 写入流程：补 ⓪ 规则入库 + 背书连边
- [x] 6.4 `openspec validate unified-ingest --strict` 通过；归档后 delta 正确应用到 `openspec/specs/write-pipeline/spec.md`

## 7. 归档后修订：撤销冗余公开入口（见 design.md D8）

- [x] 7.1 删 `MCS.ingest_event` / `ingest_source` + `WritePipeline.ingest_event` / `ingest_source`（保留私有 `_build_*` / `_connect_endorsement_edges`）
- [x] 7.2 删 `MemoryStore.learn_event`（零调用方）+ 清 `mcs_agent/memory.py` 的 `EventData` import
- [x] 7.3 删 MCP `ingest_event` 工具 + `_do_ingest_event`（回到 `mcp-server` spec「含且仅含 query / ingest」）
- [x] 7.4 删 `tests/test_ingest_event.py` / `test_ingest_source.py`；修 `test_mcp_server.py` 工具集断言为 `{query, ingest}`
- [x] 7.5 文档回灌：api-reference / mcp-server / architecture / getting-started 去掉这两个公开入口及相关注
- [x] 7.6 全量测试通过（616）、无 live spec 改动（删除项本就无 spec 契约；MCP 工具集回归与 spec 一致）
