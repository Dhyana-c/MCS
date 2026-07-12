# Design: work-narrative-events

> 配套 `proposal.md`。**依赖 `multi-universe-graph`**（`universe` 字段、per-universe 隔离、`work_id` 判定就位）。给每 universe 自己的事件层 + 作品叙事事件 LLM 抽取 + 叙事时间线。

## 背景（一句话）

`multi-universe-graph` 解决了虚构污染，但故意留下作品时序缺口（作品 universe 纯核心图、无作品事件）。本 change 补上：per-universe 事件层 + 作品叙事事件 LLM 抽取 + 叙事时间线。

## 关键设计决策

### D1：per-universe 事件层——给作品时序结构化落点

`core-graph-time-attribution` 确立"带时间的发生 MUST 归事件层"，但当前事件层只装用户真实经历（帧相对），作品叙述发生无处落点。本决策给**每个 universe 自己的事件层**：

```
   __reality__ universe                    <work_id> universe（如 三国演义）
   ┌────────────────────┐                  ┌────────────────────┐
   │ 核心图（概念/事实） │                  │ 核心图（概念/事实） │
   │  + 事件层           │                  │  + 事件层           │
   │    （摄入行为事件   │                  │    （叙事事件       │
   │     timestamp=真实  │                  │     timestamp=纪年  │
   │     ISO 时间）       │                  │     如"200年"）     │
   └────────────────────┘                  └────────────────────┘
   每条时间轴独立、universe 间时间不互染（帧相对扩展，见 D6）
```

- **现实摄入事件**（`u="__reality__"`）："今天读了演义"——**规则**入库（`_build_event_node`，timestamp=真实 ISO）。**不变**。
- **作品叙事事件**（`u=<work_id>`）："200 年曹操杀吕伯奢"——**LLM 抽取**（见 D2），timestamp=作品纪年。**新增**。
- 作品事件有**结构化 timestamp**（纪年），叙事时间线可可靠排序（D5）——这是选 per-universe 事件层而非"事实 narr_time 字段"的关键：事实的时间在 content 自由文本（time-attribution）、不可排序；事件层给结构化锚。

### D2：作品叙事事件 LLM 抽取——铁律精确化 + WorkEventDraft（P5 修复）

当前铁律"事件 / source 不经 LLM"指**摄入行为事件**（结构记录：这次 ingest 了这个动作）。作品叙事事件是**从作品文本语义识别时序性发生**（哪些是带时间的叙述、抽纪年 / 参与者），是语义抽取、本就该 LLM。铁律精确化：

> 事件产生分流：**现实摄入事件**不经 LLM（规则，`_build_event_node`）；**作品叙事事件**经 LLM 抽取（仅 `work_id` 存在时启用）。

**P5 修复（产出 dataclass）**：作品叙事事件 LLM 抽取产出 **`WorkEventDraft`**（`name` / `content` / `narr_timestamp` / `participants`）——

- **不复用 `EventData`**：`EventData` 的 docstring 明文"**不经 LLM** 的规则入库结构输入"（decisions.py L108），作品叙事事件走 LLM、语义冲突。
- **不复用 `ConceptDraft`**：`ConceptDraft` 是概念 / 事实（`node_class` 仅概念 / 事实、**无 timestamp 字段**，decisions.py L17），承载不了带纪年的事件。
- `WorkEventDraft` 是"LLM 抽取的带纪年叙述发生"的承载，与 `EventData`（规则摄入）、`ConceptDraft`（概念 / 事实抽取）并列、语义不混。

**建节点**：扩展 / 新增建事件节点原语，消费 `WorkEventDraft` → 建事件节点（`universe=work_id`、`node_class=事件`、`event_meta.timestamp=纪年`、参与者落 `event_meta` / extras）；背书边连参与者 / 相关概念（同 universe 内）。落实 time-attribution「带时间发生归事件层」在作品 universe 的缺口；其去时间化版本 MAY 并存为作品核心事实（谓词落 content，与 time-attribution 一致）。

**抽取机制**：ingest 作品 content（`work_id` 非空）时，扩展抽取（`extract_concepts` 增事件输出 / 或新增 `extract_work_events` purpose）从文本识别"带时间的叙述发生"。prompt 携带 `work_id` 上下文 + 纪年举例。

**否决"所有事件都 LLM"**：摄入行为事件保持规则（结构记录，非语义；每次 ingest 必建、LLM 化有成本无收益）。

### D3：timestamp 口径放宽（P6 修复）

`event_meta.timestamp` 不再强制 ISO 8601。按 universe 内时间语义：

- 现实 universe：ISO 8601（供 `get_related_events` 时间倒排）。
- 作品 universe：作品纪年字符串（"200 年" / "建安五年"，不强制 ISO）。

`EventData` / `event_meta` 的 timestamp 约定放宽为"universe 内时间语义字符串"。`event_sort_key` 对非 ISO timestamp MUST 容错（解析失败 fallback、不抛）。

### D4：get_related_events universe 感知（P6 修复）

`get_related_events(node_id, universe=None, limit=None)` 增 universe 过滤——只返回同 universe 事件：

- 既有 `"__reality__"` 行为：`get_related_events(核心节点)` 默认 `universe="__reality__"`（或从节点继承），时间倒排 ISO。
- 作品 universe：`get_related_events` 走 universe 过滤，**避免作品事件卷入并用 ISO 排序坏掉**。

`get_related_events` 时间倒排仅在 `"__reality__"` 内保证；作品 universe 事件排序由叙事时间线视图（D5）负责。

### D5：叙事时间线——作品事件层按 timestamp 排序（查询期组装）

叙事时间线 = **在某作品 universe 的事件层，取其事件、按 `timestamp`（作品纪年）排序**，查询期组装、**不落图**（不引入时间线 / 递归节点）。

- 排序锚 = 事件 `timestamp`（结构化纪年），非事实 content 自由文本——可靠。
- 事实本体仍挂各自概念（演义曹操 —关联— 各事实 / 事件），时间线是查询投影，**同一事件只存一份**（作品 universe 内）。
- MUST NOT 把作品纪年盖到用户时间轴（D6 帧相对）。

### D6：帧相对扩展——每 universe 一条独立时间轴

帧相对原为"用户帧 vs 叙述帧"（叙述时间不进用户时间轴）。扩展为：**每 universe 一条独立扁平时间轴**（`"__reality__"` = 真实 ISO 时间、作品 = 作品纪年），universe 间时间不互染、每帧仍扁平（不引入递归节点，守 design §3.3）。

## 风险落实

1. **作品纪年非 ISO 8601**（D3 / D5）：时间线排序按 universe 内 timestamp 语义（现实按真实时间、作品按作品纪年字符串 / 解析）；`get_related_events` 倒排仅 `"__reality__"` 保证；纪年归一化（如"建安五年 → 200 年"）留 Phase 2。
2. **作品事件 LLM 抽取质量**（D2）：漏抽 / 纪年误判 / 把非事件当事件。prompt 明确"带时间的叙述发生 + 作品纪年"举例；测试覆盖；prompt 携带 `work_id` 上下文。
3. **`WorkEventDraft` 与 `EventData` / `ConceptDraft` 边界**（D2 / P5）：明确不复用、各自语义；测试覆盖"作品事件走 LLM 产 `WorkEventDraft`、摄入事件走规则产 `EventData`"。
4. **`get_related_events` universe 过滤**（D4 / P6）：测试覆盖"作品事件不被 `"__reality__"` `get_related_events` 卷入"。

## 被否决方案

- **事实 `narr_time` extension 字段**：违反 time-attribution「时间在 content」哲学；且事实本就该是去时间化的稳定核心——带时间的发生该归事件层（D1）。事件层给结构化 timestamp 才是正解。
- **解析事实 content 时间排序**：LLM content 格式不一、没时间的事实定不了位——脆弱。
- **复用 `EventData` 承载作品事件**：语义冲突（`EventData` = 不经 LLM 的规则入库）。
- **复用 `ConceptDraft` 承载作品事件**：无 timestamp 字段、语义是概念 / 事实。
- **所有事件都 LLM**：摄入行为事件是结构记录，LLM 化有成本无收益。

## 不变量与边界

- **核心不变量不变**（`multi-universe-graph` 已精确为单 universe 内；本 change 不动）。
- **铁律一（估算 == 渲染）不变**；**铁律二（聚类 LLM 语义）不变**。
- **铁律精确化**："事件不经 LLM" → "现实摄入事件不经 LLM；作品叙事事件经 LLM 抽取"（D2）。
- **帧相对扩展**为每 universe 独立时间轴（D6）。
- **边极简不变**：仍仅 `关联` / `互斥`。
- **依赖 `multi-universe-graph`**：必须先实现并归档。
