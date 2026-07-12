# Implementation Tasks

> **前置依赖**：`multi-universe-graph` 已实现并归档（`universe` 字段、per-universe 隔离、`work_id` 判定就位）。

## 0. 数据结构（WorkEventDraft + timestamp 口径）

- [ ] 0.1 `mcs/entities/decisions.py`：新增 `WorkEventDraft` dataclass（`name: str` / `content: str` / `narr_timestamp: str | None`（作品纪年，如"200 年" / "建安五年"）/ `participants: list[str] = field(default_factory=list)`）——作品叙事事件 LLM 抽取产出。与 `EventData`、`ConceptDraft` 并列、语义不混。
- [ ] 0.2 `mcs/entities/decisions.py`：`EventData.timestamp` docstring 放宽——不再强制 ISO 8601，改为"universe 内时间语义字符串"（现实 ISO / 作品纪年）；字段类型不变（`str | None`）。

## 1. 作品叙事事件 LLM 抽取（work_id 非空时启用）

- [ ] 1.1 `mcs/core/write_pipeline.py`：`work_id` 非空时启用作品事件抽取（扩展 `extract_concepts` 增事件输出 / 或新增 `extract_work_events` purpose），从作品文本识别"带时间的叙述发生" → 产 `WorkEventDraft` 列表。抽取 prompt 携带 `work_id` 上下文 + 纪年举例。
- [ ] 1.2 新增 / 扩展建事件节点原语：消费 `WorkEventDraft` → 建事件节点（`universe=work_id`、`node_class=事件`、`event_meta.timestamp=纪年`、参与者落 `event_meta` / extras）；背书边连参与者 / 相关概念（同 universe 内）。
- [ ] 1.3 抽取出的作品事件经守门（同 universe 内）；与本次概念 / 事实同 universe（`work_id`）。

## 2. get_related_events universe 感知（P6）

- [ ] 2.1 `mcs/core/store.py` + `mcs/stores/{in_memory,sqlite_store}.py`：`get_related_events(node_id, universe=None, limit=None)` 增 `universe` 参数——只返回同 universe 事件（避免作品事件卷入并用 ISO 排序坏掉）。
- [ ] 2.2 `event_sort_key` 对非 ISO timestamp 容错（解析失败 fallback、不抛）。
- [ ] 2.3 `get_related_events` 时间倒排仅在 `"__reality__"` 内保证；作品 universe 事件排序由叙事时间线（§3）负责。

## 3. 叙事时间线（作品事件层按纪年排序，查询期组装）

- [ ] 3.1 新增时间线组装（查询期，不落图）：输入 `universe` → 取该 universe **事件层**事件 → 按 `timestamp`（作品纪年）升序 → 返回虚拟序列。
- [ ] 3.2 排序口径：现实 universe 按 ISO；作品 universe 按作品纪年字符串 / 解析（纪年归一化如"建安五年 → 200 年"留 Phase 2）。
- [ ] 3.3 时间线 MUST NOT 创建节点、MUST NOT 污染用户真实时间轴；挂为 agent 工具或 query 入口的视图模式。

## 4. 测试（含边界，`.venv\Scripts\python.exe -m pytest -q`）

- [ ] 4.1 **现实摄入事件规则产生**（`u="__reality__"`、不调 LLM）+ **作品叙事事件 LLM 抽取**（`u=<work_id>`、带作品纪年 timestamp、落作品事件层、产 `WorkEventDraft`）。
- [ ] 4.2 **叙事时间线按作品纪年排序**（取作品事件层、查询期组装、不落节点）。
- [ ] 4.3 每 universe 独立时间轴（演义"200 年"不进现实时间轴、现实"今天"不进演义时间轴）。
- [ ] 4.4 作品纪年非 ISO 排序口径（"200 年" / "建安五年"可排序、不抛）。
- [ ] 4.5 `get_related_events` universe 过滤（作品事件不被 `"__reality__"` `get_related_events` 卷入）。
- [ ] 4.6 `WorkEventDraft` 不复用 `EventData` / `ConceptDraft`（语义边界）。
- [ ] 4.7 文本转述时间不盖用户时间轴（"今天读了讲三年前故事的书"——只有"今天读书"落用户时间轴，"三年前的故事"若有 `work_id` 走作品事件 / 否则核心事实）。

## 5. 文档（保证代码与文档统一）

- [ ] 5.1 `docs/graph-model-design.md`：§3.3 双层 per-universe 事件层 + 作品事件 LLM 抽取；新增叙事时间线段（作品事件层按纪年）；§5.1 ingest 增作品事件抽取步骤；§7 已知边界补"作品纪年非 ISO"、"作品事件抽取质量"。
- [ ] 5.2 `CLAUDE.md` 宪法：「产生方式」精确化事件分流（现实摄入事件规则、作品叙事事件 LLM）；「时序帧相对」扩展为每 universe 独立时间轴；总体流程 ingest 补作品事件抽取。
- [ ] 5.3 `docs/memory-agent.md`：工具表补叙事时间线视图。

## 6. 验收

- [ ] 6.1 `openspec validate work-narrative-events --strict` 通过。
- [ ] 6.2 `.venv\Scripts\python.exe -m pytest -q` 全绿。
- [ ] 6.3 `multi-universe-graph` 已实现并归档（前置依赖）。
