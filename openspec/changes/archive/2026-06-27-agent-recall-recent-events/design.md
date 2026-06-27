## Context

记忆 agent 的 5 个导航工具中，`recall` 是唯一仍是空壳的：`MemoryStore._do_recall` 直接返回「[未实现]…依赖事件节点与热点排序」。但这一前提已不成立——

- **事件底座已就绪**（`unified-graph-schema` 已归档落地）：写管线 `_rule_ingest` 规则入库事件节点（`node_class=事件`、不经 LLM）、`extensions.event_meta.timestamp`、事件 → 核心 `关联` 背书边；`StoreInterface.get_related_events(node_id)` 定向查事件（时间倒排 + limit）。
- **接入链路已就绪**：`tools.py` 的 `_recall` handler（→ `memory.recall(limit)`）、`BUILTIN_TOOLS["recall"]` schema、`loop.py` 的 `_dispatch`、`ToolsetConfig` 默认 `enabled=None`（全 5 工具、recall 默认启用）——均无需改动。
- **唯一缺口**：`memory.py` 的 `_do_recall` 实现体 + 三处「未实现」文案（`tools.py` schema desc、`loop.py` system prompt、`memory.py` 模块 docstring）。

约束：recall 只读、经单 worker 线程（SQLite 线程亲和铁律）、不触发写 / 守门 / 裂变、不影响核心图有界性。

## Goals / Non-Goals

**Goals:**

- 实装 `_do_recall(limit)`：扫全图事件节点 → 按 `event_meta.timestamp` 时间倒排 → 取 `limit` 条 → 渲染含 id 的 LLM 可读文本。
- 排序口径 = 纯近期时间线，与 `StoreInterface.get_related_events` 对齐。
- 去掉 recall 相关「未实现」文案（schema / prompt / docstring），工具语义改为「最近事件」。

**Non-Goals:**

- 不做热度排序——事件无热度字段，掺热度需无依据加权（见 Decisions）。
- 不改工具名 `recall`（保持 handler / dispatch / 测试引用不断裂）。
- 不动 MCS 框架层（`mcs/core` / `stores` / `entities`）；不改 `query_engine` BFS 按需取事件（另一块，范围外）。
- 不做事件时间轴 UI / MCP 暴露（范围外）。

## Decisions

### D1. 纯近期时间线，不掺热度

事件节点无专门「热度」字段；可用热度信号只有事件背书的核心节点的度数。掺热度需引入 recency-vs-hot 权重，而权重无依据、需调参、难测、易反复。

- **选择**：纯按 `timestamp` 倒排，忠实「最近发生」。
- **Alt considered**：近期 + 热度加权综合分（拒——无依据权重）；纯热度排序（拒——背离「近期」语义，且 recall 明确是「最近」）。
- **后果**：工具语义从「热点事件」收敛为「最近事件」，schema / prompt 文案相应改名（工具名不变）。

### D2. 全图扫描 `get_all_nodes()` 过滤事件类

recall 是无参数（除 limit）的全局「最近事件」，不绑定某核心节点，故扫全图 `node_class=事件` 节点。

- **Alt considered**：复用 `get_related_events`（拒——那是定向查「某核心节点」背书的事件，语义不同；recall 要全局时间线）。
- 事件不进核心活跃视图（载重规则），但 `get_all_nodes()` 含事件节点（存储有、活跃视图无），故可扫到。

### D3. 时间倒排口径 = `event_meta.timestamp` 字典序倒序

`_now_iso()` 用 `datetime.now(timezone.utc).isoformat()`，统一 ISO 8601，字典序 = 时间序。

- **选择**：ISO 字符串字典序倒序；无 timestamp 者排末尾。**主键口径**与 `StoreInterface.get_related_events` 一致（系统内统一）；recall 另加 `node.id` 作次级键保确定性（见 D4），故同 timestamp 时次序可与 `get_related_events` 不同——两者都属合法时间倒排。
- **Alt considered**：解析为 `datetime` 再排序（拒——过度；且用户传入 timestamp 格式可能非标准 ISO，字典序最简且与 store 层对齐）。

### D4. 同 timestamp 加节点 id 作次级排序键

Python `sort(reverse=True)` 对相等 key 保持原列表相对顺序，但 `get_all_nodes()` 遍历顺序非契约（可能随存储实现变）。加 `node.id` 作次级 key 使结果确定、测试稳定。

### D5. 渲染复用 `_render_nodes` 口径，事件增 timestamp 行

`_render_nodes` 的「name==content 只写一份 + 带 `[id:...]`」口径与 search / associate 一致，保证 LLM 跨工具引用 id。事件 `content` = 整段 ingest 输入全文（write_pipeline ⓪），recall **全文渲染**（把真实记忆交给 LLM，不摘要）；事件需额外展示发生时间，故 recall 用一个扩展 helper（在 `_render_nodes` 口径上每条加 timestamp 行），不污染 `_render_nodes` 通用签名。全文带来的结果窗口膨胀由 D8 的 T 预算截断收敛。

### D6. 经 `_submit` 单 worker 线程

同其他原语：`recall()` → `_submit(_do_recall, limit)`。即使只读 `get_all_nodes()`，也必须经 worker 线程（SQLite 线程亲和铁律，调用方线程不触碰 MCS）。

### D7. spec requirement 标题保留 `recall 原语（热点回忆）`

openspec MODIFIED 靠 header 文本匹配现有 requirement（archive 时定位替换）。改标题有匹配失败、archive 丢内容的风险。

- **选择**：MODIFIED 时 header 保持现有 `recall 原语（热点回忆）`，内容改为「返回最近事件、纯近期口径」；标题作历史命名保留。
- **Alt considered**：RENAMED + MODIFIED 组合（拒——单 change 内对同一 requirement 组合两种 op 有执行顺序歧义）；REMOVED + ADDED（拒——语义是「修改」非「废弃 + 新增」，且需写 Migration）。
- 标题与内容的语义张力（「热点回忆」标题 vs 纯近期内容）由内容首句明确化解。

### D8. 全文渲染 + T 预算截断（至少返回最近 1 条全文）

全文渲染（D5）下，`limit` 条全文可能撑大结果窗口，故在条数 `limit` 之外再加 **token 上界 = `token_budget.T`**：时间倒排后逐条判定，达到 `limit` 条、或「纳入该条后的完整渲染文本」超 T 即停（先到先停）。

- **token 来源**：`self._mcs.query_engine.token_budget`（只读消费 `.T` + `.estimate`），不动框架层。recall 输出进结果窗口 R（默认 `R=T`）；当前用 T，若将来 `R≠T` 可改用 R。
- **估算口径 == 渲染口径（铁律一）**：对**候选完整文本** `_render_events(selected + [ev])` **整体**估算（含 header 与行间所有换行符）；MUST NOT 分段累加单条 `_render_event_line` 的 estimate——会漏 `"\n".join` 分隔符、系统性低估、致多条时 `estimate(out) > T`（实现期曾因此失守，已修）。同样 MUST NOT 套用 `TokenBudget.estimate_node`（那是 `decide_hub` 守门口径、字段不同、会误判）。
- **单条超 T 边界**：最近一条事件全文就超 T 时（罕见——单次 ingest 通常远小于 T），仍**无条件完整返回最近 1 条**，宁可略超 T 也不返回残缺/空（recall 是「最近发生了什么」，残缺最新事件无意义）；其余条目严格受 T 约束——故返回 ≥2 条时 `estimate(out) ≤ T` 恒成立。
- **Alt considered**：截断单条正文保 T（拒——破坏「全文」诉求）；跳过超 T 的找下一条（拒——牺牲「最近优先」，用户困惑最新为何不出现）；分段累加单条 line 的 estimate（拒——漏换行符、违反铁律一、曾致多条超 T）。
- `limit<=0` 视为无条数限制，仅受 T 约束 + 至少 1 条。

## Risks / Trade-offs

- **[全图扫描性能]** 事件量大时 `get_all_nodes()` 扫全量节点。→ Mitigation：事件层不聚类、时间倒排后 limit 截断；Phase 1 事件量小，可接受；未来若需优化，在 store 层加事件索引（本 change 范围外）。
- **[timestamp 格式不统一]** 调用方经 `IngestInput.timestamp` 传入非 ISO 格式时，字典序可能不准。→ Mitigation：文档注明 timestamp 应为 ISO 8601；缺省 `_now_iso()` 统一 ISO；口径与 `get_related_events` 一致（系统内一致即可，非 recall 独有）。
- **[标题语义张力]** `recall 原语（热点回忆）` 标题 vs 纯近期内容。→ Mitigation：内容首句明确「最近事件、纯近期」；标题作历史标识（spec hygiene 可后续单独处理）。
- **[单条超 T 略超]** 最近一条事件全文超 T 时 recall 输出略超 T（见 D8）。→ Mitigation：单次 ingest 全文通常远小于 T（默认 8000 tokens）；越界仅发生在最新一条、为保「最近发生了什么」的有意取舍；其余条目严格受 T 约束。

## Migration Plan

- 无数据 / 配置迁移。recall 从空壳 → 实装，公共 API `recall(limit) -> str` 签名不变，调用方（handler / loop / 测试）零改动。
- 回滚：还原 `_do_recall` 空壳 + 三处文案即可。

## Open Questions

- 未来若需真正的「热度」语义，热度信号来源待定（事件被查询触及次数需新加访问计数机制，本 change 不引入）。
