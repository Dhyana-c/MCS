# migration-audit-fixes

> 收口 code-review 在最近一系列迁移（retire-framework-query-pipeline 退役、mcp-via-agent、
> mcs-mem-extract-and-publish 拆仓、prompt-language-following、agent-context-autonomy、
> work-event-anchor-resolution）之后发现的 **15 个遗留问题**。分两簇、一个 change 扫净：
> ① **agent 时代 multi-universe 完整性缺口**（宪法级核心）；② **退役收尾遗漏**（跨核心 / bench /
> doc / spec / tests 的零散引用）。

## Why

迁移完成后做了一次全量 code-review（9-angle finder + 1-vote verify + sweep），**确认了 15 个真实
问题**（6 CONFIRMED correctness / 宪法级 + 3 PLAUSIBLE 潜伏 + 6 cleanup/doc/efficiency）。按
CLAUDE.md 工作规则 10「核心代码所有 bug 都要修、没有低优先级 bug」，必须收口。

两簇根因不同、但同属「迁移后收尾」性质：

- **A 簇（agent multi-universe 完整性）**——底层 `work-narrative-events` / `multi-universe-graph`
  两个 change 落了图模型的 universe 归属轴（work_id→universe、载重双类过滤、每 universe 独立时间轴），
  但 **agent 工具层（`mcs_agent/memory.py`）+ MCP 入口没跟上**：作品摄入断链（永不传 work_id → ③b
  `extract_work_events` 静默禁用）、裁决 / 回忆反查事件不传 universe（跨 universe 污染）、节点渲染不
  标 universe（agent 多轮决策缺信号）。这是宪法级正确性缺口（违载重命根 / 单 universe 时间轴封闭）。

- **B–F 簇（退役收尾遗漏）**——`retire-framework-query-pipeline` 删了框架读管线 / 4 个插件类型 /
  `select_facts` 读侧 bundle / `MCS.query()`，`mcp-via-agent` 重写了 MCP 后端，但 **零散引用没扫净**：
  `_traverse` 默认值仍指向已删 bundle（latent KeyError）、locomo `__main__` 仍传已删的 `track` 形参
  （评测入口直接 TypeError）、README 仍写 `mcs.query()`（新用户照抄炸）、spec 仍引用已删的
  `PostprocessPluginInterface`、context_renderer 残留 arbitrate 死分支、memory docstring 引用已删
  `render_query_result`、bench `CapturingMemory` 退役后丢 associate 邻居致多跳指标失真、mcp shutdown
  与 in-flight chat 竞态致 [error] 风暴、测试 fake 签名滞后潜伏 TypeError、13 个 prompt 语言跟随段
  + node_class 映射重复、context.py 热路径 O(n²) token 重算。

## What Changes

六组、全部向后兼容（核心公共 API 仅做可选参数扩展，老调用零改动）：

- **A. agent multi-universe 完整性**（`mcs_agent/memory.py` + `mcs_mcp/server.py` + `mcs_agent/tools.py`）
  - A1 `learn` / `ingest_structured` / `run_ingest` / `learn` 工具加可选 `work_id` 透传 → 触发 ③b
  - A2 `_do_arbitrate` 的 `get_related_events` 传 `universe=首事实.universe`
  - A3 `_do_recall` + `recall` 工具加 universe 过滤（默认 `__reality__`）+ 渲染标 universe
  - A4 `_render_nodes` 在非现实 universe 时标 `[universe:xxx]`

- **B. mcp shutdown 竞态**（`mcs_agent/memory.py` + `mcs_agent/loop.py`）
  - B1 `MemoryStore` 加 `_closed` sentinel + `MemoryShuttingDown` 异常；chat loop 收到信号优雅提前
    收尾（`termination=shutting_down`），不再 [error] 风暴空转至 max_turns

- **C. retire-framework 退役收尾**（`mcs/core/query_engine.py` + `mcs/core/context_renderer.py`）
  - C1 `_traverse` 默认 `select_purpose` 改 `select_facts_write`
  - C2 删 `context_renderer._ALL_SUMMARY_PURPOSES` arbitrate 死分支 + 孤儿测试 + spec 枚举
  - C3 删 `_run_preprocess` 死壳（方法 + 2 调用点 + 1 测试）

- **D. bench 退役收尾 + 指标修复**（`bench/golden_cage/runner.py` + `bench/multihop_rag/scripts/agent_case_study.py` + `bench/locomo/__main__.py`）
  - D1 `CapturingMemory._do_associate` 捕获 associate 邻居节点（渲染仍走基类，agent 行为零变化）
  - D2 `locomo/__main__.py` 删已退役的 `track` 形参 + argparse + docstring

- **E. 文档 / spec 漂移**（`README.md` + `openspec/specs/bench-doc-rerank-plugin/` + `mcs_agent/memory.py` docstring + `docs/select_facts_model_differences.md` + `bench/locomo/README.md`）
  - E1 README 顶层快速上手 `mcs.query()` → `query_engine.locate_seeds`
  - E2 `bench-doc-rerank-plugin` spec 删 `PostprocessPluginInterface` 引用（收敛到纯函数现状）
  - E3 memory docstring + select_facts V4 文档 + locomo README 检索轨漂移

- **F. tests fake + cleanup / efficiency**（`tests/test_agent_*.py` + `mcs/prompts/` + `mcs_agent/context.py`）
  - F1 3 处 `_FakeMemory.associate` 改签名加 `limit`（其余 4 处已正确不动）
  - F2 新建 `mcs/prompts/_common.py`：`NODE_CLASS_BY_LABEL` 去重 + `language_follow_clause(subject, extra)` 统一 13 个 prompt 语言跟随段
  - F3 `context.py` assemble/_render 增量记账（消除 O(n²) 重算）+ `_do_associate` 批量 `get_nodes`（消除 N+1）

## Impact

- **公共 API**：仅 A 簇扩展可选参数（`learn(text, work_id=None)` / `ingest_structured(content, ts, work_id=None)` / `run_ingest(text, work_id=None)` / `recall(limit, universe=__reality__)`），全部向后兼容。`mcs-mem`（已发布 0.1.1，外部 repo）依赖 `ingest_structured(content, timestamp)` 位置参数——可选第三参不破坏。B1 新增 `MemoryShuttingDown` 异常（仅 `mcs_agent/loop.py` 内部消费）。
- **核心不变量**：A 簇修复**强化**宪法（载重命根 / 单 universe 时间轴封闭 / universe 归属轴对 LLM 可见），不破坏铁律一（估算口径==渲染口径——A4 universe 标签同步进 estimate、F3 增量记账对同一文本复用同一 count 结果）。
- **存储 / 数据**：零迁移。所有修复要么是运行时过滤（A2/A3）、要么补缺失能力（A1 之前根本传不进 work_id）、要么纯文档 / 死代码清理。存量图库（含 bench）由框架路径正确建过、无需重建。
- **bench 指标**：D1 修复后 associate 邻居重新进入 touched 集，多跳 `reached_gold` / `hit@k` 会**上升**（反映真实可达性，是修复期望非回归）；历史 results.jsonl 口径变更需标注，查询阶段需重跑（图不变）。
- **spec delta**：7 个 capability（memory-agent / mcp-server / lightweight-query / llm-interaction / multihop-rag-eval / locomo-eval / bench-doc-rerank-plugin）；纯内部 DRY（F2）与效率（F3）无契约变化（op=NONE）。
