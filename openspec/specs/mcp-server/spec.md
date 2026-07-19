# mcp-server Specification

## Purpose
TBD - created by archiving change mcp-server. Update Purpose after archive.
## Requirements
### Requirement: 从配置构建并启动 MCP server

系统 SHALL 提供 MCP（stdio）server 入口，启动时从 `MCS_CONFIG` 环境变量（或 `--config` CLI 参数）指向的 YAML 经 `MCSConfig.from_file` + **mcs_agent 构造体系（`create_agent`，复用 MCS yaml 反推 `LLMConfig`）** build 出 `MemoryAgent` 后开始服务。配置缺失 / 文件不存在 / build 失败 / LLM 反推失败 MUST 清晰报错并以非零码退出。进程退出（含异常路径）MUST 调 `agent.memory.shutdown()`。

#### Scenario: 从 MCS_CONFIG 构建

- **WHEN** 设置 `MCS_CONFIG` 指向有效 YAML（`plugin_configs` 含 `{deepseek|ollama|claude}_llm` 之一）并启动 server
- **THEN** MUST 经 `MCSConfig.from_file` + `create_agent` build 出 `MemoryAgent` 并进入服务态

#### Scenario: 缺配置清晰退出

- **WHEN** 未设 `MCS_CONFIG` 且未给 `--config`
- **THEN** MUST 报清晰错误并非零退出；MUST NOT 以无效状态启动

---

### Requirement: 暴露 query 与 ingest 工具

server SHALL 暴露两个 MCP 工具：`query(query: str) -> str` 与 `ingest(text: str) -> str`。本期 MUST NOT 暴露其他工具或高级参数（如 `existing_context`）。

#### Scenario: 列出工具

- **WHEN** 客户端 list tools
- **THEN** MUST 含且仅含 `query` 与 `ingest`（各带描述与字符串入参 schema）

---

### Requirement: ingest 返回简明状态摘要

`ingest` 工具 SHALL 调 `agent.memory.learn(text)` 透传其返回字符串；摘要格式由 `mcs.rendering.format_ingest_status` 决定（渲染纯函数下沉到 `MemoryStore.learn` 委托、文本格式与旧版逐字一致），数据源为 `WriteContext` 真有字段（`len(changed)` 新增 / 合并节点、`len(concepts)` 抽取概念、`persisted`）。MUST NOT 在 server 内重复实现该摘要逻辑；MUST NOT 报边计数；MUST NOT 走 `agent.chat`（不经 agent ReAct loop——但 `memory.learn` 内部 `mcs.ingest` 仍走 MCS 写管线的 LLM 抽取，属必然）。

#### Scenario: ingest 回状态

- **WHEN** 调用 `ingest(text)` 成功
- **THEN** 返回值 MUST 是含写入概要（节点 / 概念计数、`persisted`）的简短字符串；MUST NOT 是原始 `WriteContext`；MUST NOT 含边计数
- **AND** MUST 经 `agent.memory.learn`（非 `mcs.ingest` 直调、非 `agent.chat`）

---

### Requirement: 工具调用串行化与线程亲和

MCS 非线程安全（共享内存图）且 SQLite 连接绑定创建线程。走 agent 后 MCS 实例归 `MemoryStore` 持有，**线程亲和 + 串行 SHALL 由 `MemoryStore` 自带的单 worker 线程（`max_workers=1`）保证**（MCS 构造与全部原语经 `MemoryStore._submit` 在其 worker 内同线程串行执行）；`mcs_mcp` 的职责仅剩「stdio 事件循环不被阻塞」——异步工具处理器把 `agent.chat` / `agent.memory.learn` 经 `asyncio.to_thread` offload。MCS / SQLite 全部访问 MUST 经 `MemoryStore._submit` 发生在 `MemoryStore` worker 线程；MUST NOT 在 `mcs_mcp` 层自建 executor 包 agent 调用、MUST NOT 复用 `agent.memory._executor`（私有、破坏封装）。

#### Scenario: MemoryStore 段串行、LLM 段可并发

- **WHEN** 两次 `query` 工具调用几乎同时到达
- **THEN** 二者对 MCS 的访问（经 `MemoryStore._submit`）MUST 严格串行不交错
- **AND** 二者的 LLM 调用段 MAY 并发（各自在外层线程跑、不触 MCS）

#### Scenario: MCS 访问线程一致

- **WHEN** server 处理任意工具调用
- **THEN** 对 MCS / SQLite 的访问 MUST 经 `MemoryStore._submit` 发生在 `MemoryStore` worker 线程
- **AND** MUST NOT 触发 SQLite 跨线程错误（`check_same_thread`）

#### Scenario: 慢调用不阻塞事件循环

- **WHEN** 一次 `ingest` / `query` 正在跑多轮 LLM（耗时）
- **THEN** stdio 事件循环 MUST 不被阻塞（调用经 `asyncio.to_thread` 在默认线程池执行）

---

### Requirement: 单次工具异常隔离

单次工具调用（`query` → `agent.chat` / `ingest` → `agent.memory.learn`）抛异常 SHALL 被捕获并转为 MCP 错误响应（`[error] ...` 文本）；server MUST NOT 因此崩溃，MUST 能继续服务后续调用。保证分两层：① agent 内部异常隔离（ReAct loop 内工具异常隔离为 `[error]` 回灌、LLM 调用失败降级、不向调用方抛）；② `asyncio.to_thread` 外层 try/except 外壳兜底罕见未隔离异常（构造残留 / `on_trace` 抛 `BaseException` / future 取消）转 `[error]` 文本。

#### Scenario: 工具异常不崩 server

- **WHEN** 某次 `query` / `ingest` 内部抛异常（agent 内未隔离的或外层兜底的）
- **THEN** 客户端 MUST 收到 `[error]` 文本响应（含简明原因）
- **AND** server MUST 仍可处理下一次调用（`asyncio.to_thread` 外壳隔离、stdio 事件循环不崩）

### Requirement: MCP 为可选依赖、stdio 传输与入口

MCP server SHALL 作为**顶层独立包 `mcs_mcp`** 提供，**后端依赖 `mcs_agent`**（项目内模块、随 `mcs-core` 发行物发行）。其所需的 `mcp` 与 `PyYAML` SHALL 为可选依赖（`[mcp]` extra），核心库 MUST NOT 强制依赖。server SHALL 用 stdio 传输，并提供 `mcs-mcp` 控制台入口（目标 `mcs_mcp.server:main`）与 `python -m mcs_mcp` 启动方式。`mcp` 缺失时入口 MUST 报含安装指引（`pip install mcs[mcp]`）的清晰错误。`mcs_mcp` SHALL 仅 import `mcs_agent.{builder, loop, llms}`（及间接 `memory`），**MUST NOT** import `mcs_agent.app`（会拉 fastapi / pydantic / uvicorn）。

#### Scenario: 顶层包与入口

- **WHEN** 启动 MCP server
- **THEN** MUST 可经 `mcs-mcp` console 入口或 `python -m mcs_mcp` 启动
- **AND** server 代码 MUST 位于顶层包 `mcs_mcp`，MUST NOT 位于 `mcs/mcp`

#### Scenario: 缺 mcp 给安装指引

- **WHEN** 未安装 `mcp` 时运行 `mcs-mcp`
- **THEN** MUST 报错且提示安装 `mcs[mcp]`；MUST NOT 是裸 ImportError 无指引

#### Scenario: 核心库不因 MCP 受影响、不拉 HTTP 栈

- **WHEN** 未安装 `mcp` / `PyYAML`
- **THEN** `import mcs` 与既有功能 MUST 不受影响
- **AND** 因 `mcs_mcp` 在核心库之外，`import mcs` MUST NOT 触及任何 mcp 相关模块
- **AND** `import mcs_mcp.server` MUST NOT 间接拉 fastapi / pydantic / uvicorn（仅 import `mcs_agent.builder` / `loop` / `llms`，不 import `mcs_agent.app`）

---

### Requirement: 后端为 mcs_agent

`mcs_mcp` 的工具后端 SHALL 全部经 `mcs_agent` 构造体系构建的 `MemoryAgent`：`query` → `agent.chat`、`ingest` → `agent.memory.learn`。`mcs_mcp` 的直接 import SHALL 限于 `mcs_agent.{builder, loop, llms}`（公开 API 边界）+ `mcs.entities.config.MCSConfig`（反推 `LLMConfig` 必需）；MUST NOT 直接 import `mcs.query` / `mcs.ingest` / `mcs.presets.Phase1Builder` / `mcs.rendering`（`render_query_result` / `format_ingest_status`）。（`mcs_agent` 内部调 `mcs.core`——如 `memory.learn` → `mcs.ingest`——是实现细节、非 `mcs_mcp` 直接依赖。）`mcs_agent.app` 的禁 import（避免拉 fastapi）见「MCP 为可选依赖、stdio 传输与入口」requirement。

#### Scenario: MCPServer 持有 MemoryAgent

- **WHEN** 构造 `MCPServer(config_path)` 成功
- **THEN** MUST 经 `create_agent` 构造并持有 `MemoryAgent`（而非 `MCS` 实例）

#### Scenario: 不直接 import mcs 框架

- **WHEN** 审查 `mcs_mcp/server.py` 顶层 import
- **THEN** MUST NOT 出现 `from mcs.presets` / `from mcs.rendering` / `from mcs.core.mcs` / `mcs.query` / `mcs.ingest`
- **AND** 对 `mcs` 的直接 import 仅限 `from mcs.entities.config import MCSConfig`（反推必需）
- **AND** MUST NOT 出现 `from mcs_agent.app`（避免拉 fastapi / pydantic / uvicorn）

---

### Requirement: query 工具委托 agent 多步探索

`query` 工具 SHALL 调 `agent.chat(query)` 并**原样返回其答复字符串**（agent ReAct 多步探索后的自然语言答复，含 `[id:...]` 存根引用为合法产物）。MUST NOT 在 server 内渲染 `Subgraph` / 调 `mcs.query` / `render_query_result` / `ContextRenderer`；MUST NOT 包装 / 截断 / 再渲染 agent 答复；返回值 MUST 是 `str`、MUST NOT 是 dict / `Subgraph` / 原始对象。agent 达 `max_turns` 未收敛时返回 forced 兜底文本（如「达到最大轮次」），属 agent 正常降级、非错误响应、客户端不应据此重试。

#### Scenario: query 委托 agent.chat 原样透传

- **WHEN** 调用 `query("...")` 且 `agent.chat` 返回字符串 `R`
- **THEN** 工具返回值 MUST 逐字等于 `R`（`out == R`）
- **AND** MUST NOT 包装、截断或再渲染

#### Scenario: agent 降级文本非错误

- **WHEN** agent 达 `max_turns` 返回 forced 兜底文本
- **THEN** 工具 MUST 原样返回该文本（非 `[error]` 响应）
- **AND** 客户端不应据此重试（docs 明示）

---

### Requirement: LLM 复用 MCS yaml 反推

`MCPServer` 构造期 SHALL 从 `MCSConfig.plugin_configs` 识别 `{deepseek|ollama|claude}_llm` 键反推 `LLMConfig`（provider / model / api_key / base_url / auth_token），喂 `create_agent` 构造 agent chat LLM。MUST NOT 要求额外 `AGENT_LLM_*` env 或新增配置文件；MUST NOT 静默取第一个 LLM（防 silent pick wrong LLM）。反推 SHALL 用 `AGENT_LLM_REGISTRY` 作 provider 合法集（MUST NOT 硬编码字符串）；claude 优先取 `auth_token`（Bearer）、次选 `api_key`。

#### Scenario: 反推成功 build agent

- **WHEN** YAML 的 `plugin_configs` 含单个 `deepseek_llm`（或 `ollama_llm` / `claude_llm`）段
- **THEN** MUST 反推出对应 `LLMConfig` 并成功 build `MemoryAgent`

#### Scenario: 无 LLM 早失败

- **WHEN** YAML 的 `plugin_configs` 不含任何 `{deepseek|ollama|claude}_llm` 段
- **THEN** 启动 MUST 报清晰错误（提示需配 `_llm` 段）并以非零码退出
- **AND** MUST NOT 静默继续

#### Scenario: provider 不支持早失败

- **WHEN** YAML 配了 `glm_llm` / `qwen_llm` 等 provider 不在 agent 支持集
- **THEN** 启动 MUST 报清晰错误（列支持集）并以非零码退出

#### Scenario: 多 LLM 歧义早失败

- **WHEN** YAML 同时配多个 `*_llm` 段且 `write_llm` 无法消歧（不在候选内）
- **THEN** 启动 MUST 报清晰错误（列歧义插件名 + 指引仅保留一个）并以非零码退出
- **AND** `write_llm` 在候选内时 MUST 按 `write_llm` 消歧（剥 `_llm` 后缀落 provider）

---

### Requirement: 进程退出 shutdown 路径

进程退出（含异常路径）MUST 调 `agent.memory.shutdown()`（**不是** `agent.shutdown`——`MemoryAgent` 无此方法）。SHALL 在 `main` 同步 finally 块调；shutdown 内 worker 线程关 MCS（SQLite 线程亲和）后 `executor.shutdown(wait=True)`。SHALL 注册 `SIGTERM` → `KeyboardInterrupt`（POSIX；Windows no-op）保证 finally 在强制退出下可达。MUST NOT 依赖进程自然退出（atexit 顺序不可靠、SQLite 可能未 close 致 WAL 残留 / 锁）。

#### Scenario: 正常退出调 shutdown

- **WHEN** server 正常退出（EOF / SIGINT / 经转换的 SIGTERM）
- **THEN** `main` finally MUST 调 `agent.memory.shutdown()` 一次
- **AND** MCS / SQLite MUST 在 `MemoryStore` worker 线程内关闭

#### Scenario: 构造失败跳过 shutdown

- **WHEN** `create_agent` 构造失败（如 LLM 反推失败）
- **THEN** MUST 以非零码退出；MUST NOT 调 `agent.memory.shutdown()`（无 agent 持有）
- **AND** `AgentBuilder.build` 部分失败（步骤 3/4）时 MUST 兜底 `memory.shutdown()` 清理已建 `MemoryStore`（防泄漏）

