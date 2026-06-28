## Context

个人记忆系统 4 片拆分的 **Slice 2（整合入图）**，叠在 Slice 1（捕获层）之上。Slice 1 把消息落成当天 MD 碎片；本片把碎片去噪后沉淀进图谱。

已对照代码 / 宪法核实的约束：
- **跨层契约（被依赖不变量）**：依赖 `mcs.IngestInput(content, timestamp)` 的 `timestamp` 字段
  落事件 `extensions.event_meta.timestamp`（已核实 `mcs/entities/decisions.py:178` +
  `mcs/core/write_pipeline.py:406` `data.timestamp or _now_iso()`）。`mcs` 重构 IngestInput 时
  MUST 保此契约，否则整合的"时间忠实"断裂。
- `mcs.ingest(data)` 每次必建一个新事件节点，**不幂等**。幂等由上层 tracker 保证。
- 宪法 [CLAUDE.md:43](../../../CLAUDE.md)：「每次 ingest 把整个输入记为**一个事件节点**——记录这一行为、落用户时间轴」；「概念 / 事实靠 LLM 语义抽取；**事件 / source 由规则入库、不经 LLM**、只有 content 走 LLM」。→ **事件层是原子时间轴，归并属概念层**。
- ingest **自带** LLM 概念抽取 + 守门聚类 + 带已有节点对齐（合并同义）。本片 MUST NOT 在事件输入层重复这些。
- 宪法插件体系含 `WRITE_PREPROCESS`（写入管线阶段①），但其契约 `preprocess(text)->str` 纯变换、`MUST NOT control pipeline flow (e.g. skip)`（[plugin-protocol spec:108](../../specs/plugin-protocol/spec.md)）——**丢不掉输入**，故去噪（要丢碎片）做不成插件，只能在管线外应用层做（见 D2）。
- `MemoryStore` 已有 `recall`/`search` 只读原语 + 单 worker 线程（MCS 调用经 `_submit`）。`learn(text)` 只收 str、时间盖 now。

## Goals / Non-Goals

**Goals:**
1. 把当天碎片整合进图谱，**一碎片一事件**、时间忠实
2. 去噪：丢弃噪声 / 不值得记的碎片（ingest 做不了的唯一活）
3. 单日锁定保证不重复入图
4. 默认凌晨整合「昨天」（避免孤儿）+ 手动触发，整合互斥
5. 暴露全量状态（供 Slice 4 日历）

**Non-Goals:**
- **不在事件输入层做合成 / 同义合并**——归并交 ingest 概念层（铁律二 + 事件原子性）
- 不做 LLM 语义分段（与概念抽取重复）
- 不做 force / 重整 / 历史日期重整（单日锁定）
- 不生成日记（Slice 3）；不碰 UI（Slice 4）

## Decisions

### D1: 整合管线三段——解析 → 去噪 → 逐条 ingest

```
当天 MD ──解析──▶ raw 碎片[(ts, content)]
        ──去噪(Consolidator 应用层)──▶ 保留碎片[(ts, content)]   (丢噪声，不合成不归并)
        ──逐条 mcs.ingest(IngestInput)──▶ 一碎片一事件 + 概念入图
```

**解析**：逐行 `HH:MM 内容` → `(date+HH:MM ISO, 正文)`；无法解析的行跳过 + WARNING；不调 LLM。

**一碎片一事件**：保留的碎片**逐条**入图，每条一个事件、时间 = 该碎片时间。**不合成**（多条不塌成一个），故无旧版的「合成时间塌缩」问题。归并 / 同义合并由 ingest 的概念层 + 守门聚类承担。

### D2: 去噪——Consolidator 应用层前置过滤（不走插件）

**选择**：去噪是「这条碎片值得记吗 / 是不是噪声」的**逐碎片**判定（不需全天上下文），在 **`Consolidator` 内部、ingest 调用之前**执行：对解析出的每条碎片做一次轻量 LLM 判定，**仅保留值得记的碎片送 `ingest_structured`**，噪声碎片根本不进 ingest。

**为何不是 `WRITE_PREPROCESS` 插件**（推翻上一版设想）：`WRITE_PREPROCESS` 插件契约是 `preprocess(text: str, ctx) -> str` 纯字符串变换，且 [plugin-protocol spec:108](../../specs/plugin-protocol/spec.md) 明确 `MUST NOT control pipeline flow (e.g. skip)`——**插件丢不掉一条输入**。去噪的本质是「决定某条要不要进图」=控制管线流，插件位**做不到**。故去噪只能在管线**外**（Consolidator 应用层）做，作为 ingest 的前置过滤。这不是 bespoke 妥协，是契约决定的唯一位置。

**作用域**：去噪只作用于**整合路径**（Consolidator 处理碎片时）。agent 直接 `learn` 等其他写入路径**不**经此去噪——符合预期（去噪是「日记碎片整合」特有的步骤，不是全局写入策略）。

### D3: 事件粒度与时间——一碎片一事件，时间忠实，无塌缩

每条保留碎片带 ISO `timestamp` → 落事件 `event_meta.timestamp`，recall 据此时间倒排。**不合成**故每个事件忠实对应一条原始碎片、一个真实时刻。`content` 只放正文、不含时间前缀。

> 偏离旧版：旧设计含「跨碎片合成」会把多条塌成一个事件 / 一个时间戳。本版 A1 review 后移除——合成退回概念层，事件层保持原子忠实。

### D4: 结构化 ingest 原语——`MemoryStore.ingest_structured`

`MemoryStore` 新增 `ingest_structured(content, timestamp) -> str`：worker 线程内 `wctx = self._mcs.ingest(IngestInput(content=content, timestamp=timestamp))`，返回 `wctx.event_node.id`。读写共用同一 MCS / worker。原 `learn(text)`（时间盖 now）保留不变。

### D5: 幂等——`ConsolidationTracker` 单日锁定，无 force

整合状态本地 JSON（默认 `~/.mcs_memory/consolidation_status.json`），记每日 `pending/running/done/failed` + 事件数 + 时间戳。某日 `done` 即锁定：再触发返回 `already`、不重跑、无 force、不支持历史重整。

**理由**：ingest 不幂等，重整必产生重复事件。单日锁定从源头杜绝，无需级联删除。**代价**：`done` 后改 MD 不再入图（只留 MD 层），文档须注明。

### D6: 调度——凌晨整合「昨天」，避免孤儿

**选择**：默认 cron `30 0 * * *`（每天 00:30）整合**前一日**（已完整封口的那天）。可配 / 可禁用。

**为何不是「夜间 23:00 整合当天」**（旧默认）：23:00 整合当天并 `done` 锁定后，23:00–23:59 记的碎片落同一天文件、但那天已锁——**永不入图**（孤儿）。改成凌晨整合昨天，被整合的那天已无新消息，孤儿问题根除。

**手动 `POST /consolidate` 的默认日期也改为「昨天」**（review #6）：旧版默认当天，用户不传 date 一点就锁今天、立刻踩孤儿。现与调度器对齐——无 date 默认整合昨天（安全）。**要整合今天必须显式传 `date=今天`**，且响应附 `warning`（"今天整合后即锁定，今天后续消息不会自动入图，需明天手动补整或接受其只活在 MD"）。把"明知会锁今天"这个危险动作变成**显式 opt-in**，而非默认踩坑。

### D7: 线程边界——LLM 不进 worker 线程（D2 工程约束）

去噪判定的 LLM 调用 **MUST NOT 在 MCS 的单 worker 线程内执行**（会把单 worker 阻塞整段 LLM 延迟、卡死并发读写）。线程边界：
- LLM 调用（去噪判定）→ worker 线程**外**（普通线程 / 异步）；
- `recall`/`search`/`ingest_structured`（碰 MCS）→ 经 `_submit` 进 worker。

整合互斥锁（应用级）与 worker 串行化是两层：互斥防重入整合，worker 保 MCS 线程安全。

## Risks / Trade-offs

- **[去噪只在整合路径]** agent 直接 `learn` 不经去噪（D2）→ 预期：去噪是整合特有步骤、非全局写入策略；若未来要全局过滤另议
- **[去噪误杀]** 把值得记的判成噪声 → 缓解：去噪 prompt 保守（拿不准就留）；原始碎片在 MD 保真层、可手动补
- **[改后不可重整]** D5 取舍 → 缓解：文档明示；未来另起 change 做安全级联删除 + 重建
- **[整合延迟]** 碎片记录后需等整合才可查 → 缓解：手动 `POST /consolidate` 即时入图（注意 D6 今天手动整合的孤儿提示）
- **[调度可靠性]** 进程退出则调度停 → 缓解：外部进程管理；APScheduler 可选持久化 job store
