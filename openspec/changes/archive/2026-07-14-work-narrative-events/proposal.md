## Why

`multi-universe-graph` 给节点加了 `universe` 维度，解决了虚构污染真值（误判互斥）。但它**故意留下一个缺口**：作品的**内部时序性发生**无处落点。

`core-graph-time-attribution` 确立"带时间的发生 MUST 归事件层"，但事件层当前只装**用户真实经历**（帧相对——叙述时间不进用户时间轴）。于是小说里"200 年曹操杀吕伯奢"这种带作品纪年的叙述发生，**既不能进用户事件层（帧相对）、作为事实又没有结构化时间锚**（time-attribution 让时间嵌 content 自由文本、不可排序）——当前模型对"作品内部的时序"没有干净落点。进而用户读小说想看"这部作品的叙事时间线（184 → 189 → 200 → …）"也无法组装。

`multi-universe-graph` 阶段，作品 universe 是纯核心图（概念 / 事实 / source），**无作品事件**——可工作但丢失了作品内部的时序结构。本 change 在 universe 隔离已就位的基础上，给**每个 universe 自己的事件层**，让作品时序性发生有结构化落点（作品纪年 timestamp）、叙事时间线得以组装。

## What Changes

- **per-universe 事件层**：事件层按 universe 分立——每 universe 持有自己的扁平事件时间轴（universe 间时间不互染，帧相对扩展为"每 universe 一条独立时间轴"）。事件节点带 `universe`（`multi-universe-graph` 已加）。
- **事件产生分流**（铁律精确化）：当前铁律"事件不经 LLM"指**摄入行为事件**（结构记录：这次 ingest 了这个动作，`"__reality__"`）。作品叙事事件是**从作品文本语义识别时序性发生**（哪些是带时间的叙述、抽纪年 / 参与者），是语义抽取、本就该 LLM。精确化为：
  - **现实摄入事件**（`u="__reality__"`）：规则产生（既有 `_build_event_node`，timestamp=真实 ISO）、不经 LLM——不变。
  - **作品叙事事件**（`u=<work_id>`）：LLM 抽取（仅 `work_id` 存在时启用）、不经规则——新增。
- **作品叙事事件 LLM 抽取**（P5 修复）：`work_id` 非空时，从作品文本识别"带时间的叙述发生"→ 产事件节点（`universe=work_id`、`timestamp=作品纪年`、参与者 / 发生 content）。**产出 dataclass `WorkEventDraft`**（name / content / narr_timestamp / participants）——不复用 `EventData`（其语义是"不经 LLM 的规则入库"）、不复用 `ConceptDraft`（无 timestamp、语义是概念 / 事实）。建节点原语注入 `universe=work_id` + 纪年到 `event_meta.timestamp`。
- **participants 数据流（名 → 节点 → 背书边）**：`WorkEventDraft.participants` 是**名字**列表，建事件时 MUST 解析为**同 universe（`work_id`）内**的概念节点 id 再连背书边——**复用 mug 的同名去重设施**（`existing_by_name` / `name_to_id`，限同 universe）：命中同 universe 同名概念则复用、未命中新建概念（`universe=work_id`）；参与者 id 落 `event_meta` + `事件 —关联→ 参与者概念` 背书边（同 universe 内）。**MUST NOT 跨 universe 连参与者**（作品事件只背书作品概念）。
- **timestamp 口径放宽**（P6 修复）：`event_meta.timestamp` 不再强制 ISO 8601——按 universe 内时间语义：现实 universe ISO（供 `get_related_events` 时间倒排）、作品 universe 作品纪年字符串（如"200 年" / "建安五年"，不强制 ISO）。`EventData` / `event_meta` 的 timestamp 约定放宽为"universe 内时间语义字符串"。
- **get_related_events universe 感知**（P6 修复，**与 `multi-universe-graph` 语义兼容——见下**）：`get_related_events(node_id, universe=None, limit=None)` 增**可选** universe 过滤，语义**按参数分流**：
  - **`universe=None`（默认）返回全部背书事件（含跨 universe）**——**向后兼容 `multi-universe-graph` 已实现并测试锁定的"作品 fact 定向查出处 = 现实摄入 event 亦返"语义**（`get_related_events(作品 fact)` 无参仍返 `__reality__` 摄入 event，查出处），**MUST NOT 破坏其测试**（`test_multi_universe.py` 的跨 universe 背书亦返用例）。
  - **传 `universe=U` 时才只返同 `universe` 事件**——叙事时间线（作品 universe）MUST **显式传** `universe=work_id` 过滤，避免现实 ISO 与作品纪年混排坏掉。
  - 时间倒排仅在 `universe="__reality__"` 内保证；作品 universe 排序由叙事时间线视图负责。
- **叙事时间线**：在某作品 universe 的事件层，取其事件、按 `timestamp`（作品纪年）排序——查询期组装、不落图（不引入时间线 / 递归节点）。**Phase 1 排序可靠性受纪年格式限制（诚实标注）**：`event_sort_key`（`timestamp_sort_value`）解析不了作品纪年字符串（"200 年" / "建安五年"）时**垫底、同值失序**——故 **Phase 1 仅对可解析为可比数值的纪年（如纯数字年 "184" / "200"）保证顺序；混合 / 非数字纪年（"建安五年"）需 Phase 2 纪年归一化后才可靠**。本 change 交付时间线组装骨架 + 数字年最小解析；完整纪年归一化（"建安五年 → 200"）留 Phase 2。

## Capabilities

### New Capabilities

（无）—— per-universe 事件层 / 作品事件抽取 / 叙事时间线是图模型核心契约的一部分，归 `unified-graph-schema` / `entities-package` / `store-interface`，不新增 capability。

### Modified Capabilities

- **`unified-graph-schema`**：
  - **新增** `per-universe 事件层与作品叙事事件` requirement：事件层按 universe 分立；现实摄入事件规则入库、作品叙事事件 LLM 抽取（带作品纪年 timestamp）。
  - **新增** `叙事时间线（作品事件层按纪年排序）` requirement：作品 universe 事件层按 timestamp 排序，查询期组装、不落图。
  - **修改** `概念 / 事实靠 LLM，事件 / source 靠规则` → 事件产生方式分流（现实摄入事件仍规则、不经 LLM；作品叙事事件经 LLM 抽取）。
  - **修改** `时序走字段不走边，且帧相对` → 每 universe 一条独立时间轴，universe 间时间不互染（帧相对从"用户帧 vs 叙述帧"扩展为"每 universe 独立帧"）。
- **`entities-package`**：**新增** `作品叙事事件抽取产出 WorkEventDraft` requirement → `WorkEventDraft` dataclass；`EventData.timestamp` 约定放宽为 universe 内时间语义。
- **`store-interface`**：**新增** `定向查事件按 universe 过滤` requirement → `get_related_events` 增 `universe` 参数、非 ISO timestamp 容错。

## Impact

- **代码**：
  - `mcs/entities/decisions.py`：新增 `WorkEventDraft` dataclass；`EventData.timestamp` docstring 放宽（universe 内语义）。
  - `mcs/core/write_pipeline.py`：`work_id` 非空时启用作品事件 LLM 抽取（扩展抽取 purpose 或新增 `extract_work_events`）；新增 / 扩展建事件节点原语注入 `universe=work_id` + 纪年到 `event_meta.timestamp`。
  - `mcs/core/store.py` + `mcs/stores/{in_memory,sqlite_store}.py`：`get_related_events` 增**可选** `universe` 过滤（`None` 全返兼容 mug、传参才过滤）；`event_sort_key` 现状已垫底容错（非 ISO 不抛），本 change 加**数字年最小解析**使纯数字纪年可排。
  - `mcs/core/query_engine.py` / `mcs_agent` 工具：叙事时间线视图（作品事件层显式传 `universe=work_id`、按 timestamp 排序，查询期组装）。
- **依赖**：`multi-universe-graph`（`universe` 字段、per-universe 隔离、`work_id` 判定、universe 元节点 + 注册表归一）**已实现并归档**（`archive/2026-07-12-multi-universe-graph`）——前置就绪。
- **测试**（含边界）：作品叙事事件 LLM 抽取（带纪年、落作品事件层、产 `WorkEventDraft`）；现实摄入事件仍规则产生；叙事时间线按纪年排序（**数字年可排、混合纪年 Phase 1 不保证**）；timestamp 非 ISO 排序口径；**`get_related_events(node)` 无参仍跨 universe 背书亦返（不破 mug 测试）、传 `universe=U` 才过滤**；participants 名→同 universe 概念解析（复用去重、未命中新建、不跨 universe）；每 universe 独立时间轴不互染；`WorkEventDraft` 不复用 `EventData` / `ConceptDraft`。
- **文档**：`docs/graph-model-design.md` §3.3 per-universe 事件层 + 作品事件 LLM 抽取 + 叙事时间线段；`CLAUDE.md` 宪法「产生方式」精确化事件分流、「时序帧相对」扩展为每 universe 独立时间轴。
- **API / 依赖**：新增 `WorkEventDraft`（不破坏现有）；`get_related_events` 加可选 `universe` 参数（**`None` 默认全返 = 向后兼容 mug 已锁定语义，传参才过滤**）。
- **不变量**：核心不变量不变（`multi-universe-graph` 已精确为单 universe 内）；铁律精确化"事件不经 LLM" → "摄入行为事件不经 LLM；作品叙事事件经 LLM 抽取"；帧相对扩展为每 universe 独立时间轴。
- **实现风险**（详见 design）：① 作品纪年非 ISO 8601（Phase 1 仅数字年可排、混合纪年需 Phase 2 归一化）；② 作品事件 LLM 抽取质量（漏抽 / 纪年误判）；③ `WorkEventDraft` 与 `EventData` / `ConceptDraft` 边界；④ `get_related_events` universe 过滤**须兼容 mug 已锁定的"无参跨 universe 背书亦返"语义**（`None` 全返、传参才过滤，不改默认）；⑤ participants 名→同 universe 概念解析数据流。
