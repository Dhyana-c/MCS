> ⚠️ **架构修订（change [`mcs-mem-package-extract`](../mcs-mem-package-extract/proposal.md)）**：
> 本 change 原 design「改 `mcs_agent/app.py` 加整合路由、`Consolidator` 在 `mcs_agent`」
> 已被推翻——整合模块（`consolidation` / `scheduler`）现位于独立 `mcs_mem` 包，端点经
> `mcs_mem.create_app` 挂同一 app（单向依赖 `mcs_mem` → `mcs_agent` → `mcs`）。**但**
> `MemoryStore.ingest_structured` 留 `mcs_agent`（核心库、被整合调用）。下文「改 `mcs_agent`」
> 的整合路由部分应据此理解为 `mcs_mem`。

## Why

捕获层（Slice 1 `personal-memory-system`）把消息落成当天 MD 碎片，但碎片**还没进图**——查不了、推理不了。需要一条**整合管线**：把碎片沉淀进记忆图谱。

**整合时 agent 这一层只做 ingest 真做不了、且不破坏宪法事件层语义的一件事——去噪筛选**（判定哪些碎片是噪声 / 不值得记，丢弃；ingest 全收、从不筛）。其余两件原本设想的活退回 `mcs.ingest` 自带的概念层：

- **合成**（跨碎片归并）→ 退回 ingest 概念层。宪法 [CLAUDE.md:43](../../../CLAUDE.md) 规定「每次 ingest 把整个输入记为**一个事件节点**、落用户时间轴」+「概念 / 事实靠 LLM 语义抽取」。在事件输入层合成会把多条用户行为塌成一个事件 / 一个时间戳（坏时间轴原子性），且与概念层的「带已有节点对齐、合并同义」**重复**。故**事件保持一条碎片一个**，归并在概念层自然涌现。
- **查重**（同义判定）→ ingest 本就「带已有节点对齐、合并同义」，不另造。

这样 agent 层就是一个**去噪过滤器**，在 **Consolidator 内部、ingest 之前**执行（逐碎片判去留，仅保留的送 ingest）；ingest 照常做概念抽取 + 守门聚类 + 同义合并。

> 注：去噪**不能**落 `WRITE_PREPROCESS` 插件位——该插件契约 `preprocess(text)->str` 是纯变换、`MUST NOT control pipeline flow (e.g. skip)`（[plugin-protocol spec:108](../../specs/plugin-protocol/spec.md)），丢不了输入。故去噪只能在管线**外**（Consolidator 应用层）做。

## What Changes

- 新增 **整合管线（agent-consolidation）**：读当天 MD（Slice 1 `FragmentStore.read`）→ 逐行解析 `(ts, content)` → **去噪筛选**（保留值得记的碎片）→ **逐条** `mcs.ingest(IngestInput)` 入图（一碎片一事件、时间忠实）
- **去噪在 Consolidator 内执行**（ingest 之前的应用层过滤，见 design D2）：逐碎片判定「值得记 / 噪声」，仅保留的碎片送 ingest（噪声不进 ingest、不产生事件）
- 给 `mcs_agent` 的 `MemoryStore` **新增结构化 ingest 原语** `ingest_structured(content, timestamp) -> event_id`
- 新增 **整合状态追踪**（`ConsolidationTracker`，本地 JSON）+ **单日锁定**（`done` 后不重整、无 force）
- 新增 **定时调度**（APScheduler）：默认**凌晨整合「昨天」**（`30 0 * * *`）——避开「夜间整合当天 + 单日锁定 → 当天后续消息成孤儿」的坑（见 design D6）
- 新增 HTTP 端点（挂 `mcs_agent` app）：`POST /consolidate`（**无 date 默认整合「昨天」**，与调度器一致、避免孤儿；整合今天须显式传 date 且返回 warning）、`GET /consolidate/status`、`GET /consolidate/statuses`；agent 无 `memory`/`llm` 时优雅 503（仿现有 `/graph/expand`）

## Capabilities

### New Capabilities

- `agent-consolidation`: 整合管线——解析当天 MD →（Consolidator 应用层）去噪 → 逐条 ingest 入图（一碎片一事件）；状态追踪 + 单日锁定 + `/consolidate*` 端点
- `consolidation-scheduler`: 定时整合调度——APScheduler 进程内、默认凌晨整合昨天、cron 可配、手动触发、整合互斥、随 app lifespan 起停。**拆成独立 capability 的理由**：调度**可选部署**——不装调度器仍可手动 `POST /consolidate` 整合，与 diary 的"定时软复用"模式一致；调度是整合之上的可拆装层，故独立

### Modified Capabilities

- `memory-agent`: `MemoryStore` 新增 `ingest_structured(content, timestamp) -> event_id`（worker 线程内 `mcs.ingest(IngestInput(content, timestamp))`、返回事件 id）

## Impact

- **依赖 Slice 1**（proposal 散文声明；`.openspec.yaml` 不用 `depends-on`——非 OpenSpec 标准字段）：读碎片用 `FragmentStore`；端点挂同一 `mcs_agent` app
- **改 `mcs_agent`**：`MemoryStore` 加结构化 ingest；`app.py` 加整合路由 + lifespan 起调度器；去噪在 Consolidator 应用层（不经插件）
- **新依赖**：`apscheduler`（加进 `pyproject.toml`）
- **LLM 成本**：去噪每条一次轻判 + 每条保留碎片一次 ingest（含概念抽取）；凌晨一次批量，成本有界
- **取舍**：单日锁定下，`done` 后改 MD 不再入图（改动只留 MD 保真层）——见 design D5
