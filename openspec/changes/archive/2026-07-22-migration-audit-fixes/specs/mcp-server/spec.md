# mcp-server Delta

> migration-audit-fixes：B1 shutdown 与 in-flight chat _submit 竞态（graceful 退化取代 [error] 风暴）+
> A1 ingest 工具加 work_id 透传。

## MODIFIED Requirements

### Requirement: 暴露 query 与 ingest 工具

server SHALL 暴露两个 MCP 工具：`query(query: str) -> str` 与 `ingest(text: str, work_id: str | None = None) -> str`。本期 MUST NOT 暴露其他工具或高级参数（如 `existing_context`）。`ingest` 的 `work_id` 为可选参数：非空时归该作品 universe、触发阶段 ③b 作品叙事事件抽取；省略 = 现实 universe（默认行为）。

#### Scenario: 列出工具

- **WHEN** 客户端 list tools
- **THEN** MUST 含且仅含 `query` 与 `ingest`（各带描述与字符串入参 schema；`ingest` schema 含可选 `work_id` 字段）

#### Scenario: ingest 工具的 work_id 参数

- **WHEN** 审查 `ingest` 工具 schema
- **THEN** `parameters.properties` MUST 含 `text`（required）与可选 `work_id`（string，描述「作品标注；非空时归该作品 universe、触发作品叙事事件抽取 ③b」）
- **AND** `required` MUST 仅含 `["text"]`

---

### Requirement: ingest 返回简明状态摘要

`ingest` 工具 SHALL 调 `agent.memory.learn(text, work_id=work_id)` 透传其返回字符串；摘要格式由 `mcs.rendering.format_ingest_status` 决定（渲染纯函数下沉到 `MemoryStore.learn` 委托、文本格式与旧版逐字一致），数据源为 `WriteContext` 真有字段（`len(changed)` 新增 / 合并节点、`len(concepts)` 抽取概念、`persisted`）。MUST NOT 在 server 内重复实现该摘要逻辑；MUST NOT 报边计数；MUST NOT 走 `agent.chat`（不经 agent ReAct loop——但 `memory.learn` 内部 `mcs.ingest` 仍走 MCS 写管线的 LLM 抽取，属必然）。

#### Scenario: ingest 回状态

- **WHEN** 调用 `ingest(text)` 成功
- **THEN** 返回值 MUST 是含写入概要（节点 / 概念计数、`persisted`）的简短字符串；MUST NOT 是原始 `WriteContext`；MUST NOT 含边计数
- **AND** MUST 经 `agent.memory.learn`（非 `mcs.ingest` 直调、非 `agent.chat`）

#### Scenario: ingest 透传 work_id

- **WHEN** 调用 `ingest(text, work_id="三国演义")`
- **THEN** server MUST 经 `agent.memory.learn(text, work_id="三国演义")` 透传
- **AND** 非空 `work_id` 经 learn → `mcs.ingest(IngestInput(work_id=...))` 触发 ③b 作品叙事事件抽取（详见 memory-agent delta「learn 原语」）

---

### Requirement: 进程退出 shutdown 路径

进程退出（含异常路径）MUST 调 `agent.memory.shutdown()`（**不是** `agent.shutdown`——`MemoryAgent` 无此方法）。SHALL 在 `main` 同步 finally 块调；shutdown 内 worker 线程关 MCS（SQLite 线程亲和）后 `executor.shutdown(wait=True)`。SHALL 注册 `SIGTERM` → `KeyboardInterrupt`（POSIX；Windows no-op）保证 finally 在强制退出下可达。MUST NOT 依赖进程自然退出（atexit 顺序不可靠、SQLite 可能未 close 致 WAL 残留 / 锁）。

**shutdown 与 in-flight chat 竞态的 graceful 退化**：`MemoryStore.shutdown` 先翻 `_closed` sentinel，使后续 `_submit` 抛 `MemoryShuttingDown`（而非裸 `RuntimeError('cannot schedule new futures')`）；in-flight chat（跑在 asyncio-executor 线程、不收 KeyboardInterrupt）收到 `MemoryShuttingDown` 后，`MemoryAgent._dispatch` SHALL 特化捕获并让 chat loop 优雅提前收尾（`termination="shutting_down"`、友好降级文本），MUST NOT 产生 `[error]` 工具文本风暴、MUST NOT 空转至 `max_turns`。

#### Scenario: 正常退出调 shutdown

- **WHEN** server 正常退出（EOF / SIGINT / 经转换的 SIGTERM）
- **THEN** `main` finally MUST 调 `agent.memory.shutdown()` 一次
- **AND** MCS / SQLite MUST 在 `MemoryStore` worker 线程内关闭

#### Scenario: 构造失败跳过 shutdown

- **WHEN** `create_agent` 构造失败（如 LLM 反推失败）
- **THEN** MUST 以非零码退出；MUST NOT 调 `agent.memory.shutdown()`（无 agent 持有）
- **AND** `AgentBuilder.build` 部分失败（步骤 3/4）时 MUST 兜底 `memory.shutdown()` 清理已建 `MemoryStore`（防泄漏）

#### Scenario: shutdown 期间 in-flight chat 优雅收尾

- **WHEN** `main` finally 在 in-flight chat 仍在跑（其工具调用经 `_submit` 排同一单 worker executor）时调 `agent.memory.shutdown()`
- **THEN** `MemoryStore` 经 `_closed` sentinel 让 in-flight chat 后续 `_submit` 抛 `MemoryShuttingDown`
- **AND** `MemoryAgent._dispatch` SHALL 特化捕获 `MemoryShuttingDown`（置 `_shutting_down=True`、返回友好降级文本），loop SHALL 提前 break（`termination="shutting_down"`）
- **AND** MUST NOT 产生 `[error]` 工具文本、MUST NOT 空转至 `max_turns`

#### Scenario: shutdown 后再调原语抛 MemoryShuttingDown

- **WHEN** `agent.memory.shutdown()` 已调用后，再调任何 `MemoryStore` 原语（learn / search / associate / ...）
- **THEN** MUST 抛 `MemoryShuttingDown`（非裸 `RuntimeError`），供调用方识别
