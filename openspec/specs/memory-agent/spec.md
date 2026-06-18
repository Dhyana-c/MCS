# memory-agent Specification

## Purpose
TBD - created by archiving change memory-agent-skeleton, updated by memory-agent-navigation. Update Purpose after archive.
## Requirements
### Requirement: MemoryStore 单线程包装 MCS

`MemoryStore` SHALL 在单一 worker 线程内构造 MCS 并执行其全部调用，规避 MCS 非线程安全与 SQLite 线程亲和。

#### Scenario: 所有 MCS 调用经同一 worker 线程

- **WHEN** 多次并发调用 MemoryStore 的任一原语（learn / search / associate / find_path / recall）
- **THEN** 每次 MUST 经 `ThreadPoolExecutor(max_workers=1)` 串行执行
- **AND** 调用方线程 MUST NOT 直接触碰 MCS 实例

#### Scenario: 原语返回 LLM 可读文本

- **WHEN** 调用任一 MemoryStore 原语
- **THEN** MUST 在 worker 线程内执行对应 MCS 调用并返回 LLM 可读文本（含节点 id）

---

### Requirement: MemoryStore 复用 mcp-server 渲染纯函数

`MemoryStore` SHALL 复用 `mcs.mcp.server._render_query_result`（associate）与 `_format_ingest_status`（learn）渲染结果，不重复实现。

#### Scenario: 复用而非重复实现

- **WHEN** `MemoryStore` 渲染 associate / learn 结果
- **THEN** MUST 调用 mcp-server 的渲染纯函数
- **AND** MUST NOT 自行实现等价渲染逻辑

---

### Requirement: MemoryAgent ReAct loop

`MemoryAgent` SHALL 通过 LLM tool calling 执行 ReAct 循环：LLM 返回 `tool_calls` 时执行工具并把结果回灌为 `tool` 消息；无 `tool_calls` 时返回最终答复文本；达到 `max_turns` 回退为兜底文本。

#### Scenario: 无工具调用直接答复

- **WHEN** LLM 返回无 `tool_calls` 的 assistant 消息
- **THEN** `chat()` MUST 返回该消息的 `content`

#### Scenario: 工具调用结果回灌

- **WHEN** LLM 返回 `tool_calls`
- **THEN** MUST 执行每个工具调用
- **AND** MUST 将结果作为 `tool` 消息（带 `tool_call_id`）追加到消息历史
- **AND** MUST 继续下一轮 LLM 调用

#### Scenario: 达到最大轮次回退

- **WHEN** 循环达到 `max_turns` 仍未给出最终答复
- **THEN** `chat()` MUST 返回兜底文本，MUST NOT 抛出异常

---

### Requirement: 单次工具异常隔离

单次工具调用抛出的异常 SHALL 被隔离为 `[error]` 文本回灌，不中断 ReAct loop。

#### Scenario: 工具异常不毁 loop

- **WHEN** 某次工具调用抛异常
- **THEN** MUST 将异常转为 `[error] {类型}: {信息}` 文本
- **AND** loop MUST 继续执行（不向调用方抛异常）

#### Scenario: 非法 JSON 参数

- **WHEN** 工具调用的 `arguments` 不是合法 JSON
- **THEN** MUST 返回 `[error] 工具参数不是合法 JSON`，不抛异常

---

### Requirement: LLM 调用可注入

`MemoryAgent` SHALL 接受 `llm_call(messages, tools) -> assistant_dict` 可注入 callable，而非绑定具体 LLM SDK。

#### Scenario: 测试注入 mock

- **WHEN** 测试构造 `MemoryAgent(memory, scripted_llm_call)`
- **THEN** loop MUST 使用注入的 callable，不依赖真实 LLM API

---

### Requirement: 记忆工具集（learn / search / associate / reason / recall）

`MemoryAgent` SHALL 经 `MEMORY_TOOLS` 向 LLM 暴露 5 个导航工具，分发到 MemoryStore 对应原语：

- `learn(text)` → `memory.learn`
- `search(query, mode)` → `memory.search`
- `associate(seed_id, mode)` → `memory.associate`
- `reason(source_id, target_id)` → `memory.find_path`
- `recall(limit)` → `memory.recall`

导航决策权交给 LLM：由 LLM 决定选哪个工具、哪个种子、哪种模式、哪两个节点。

#### Scenario: 分发到 MemoryStore 原语

- **WHEN** LLM 调用任一 5 工具
- **THEN** MUST 转发到对应 MemoryStore 原语（learn/search/associate/find_path/recall）

#### Scenario: 未知工具

- **WHEN** LLM 调用不在工具表中的工具名
- **THEN** MUST 返回 `[error] 未知工具：{name}`

#### Scenario: 系统提示词导航导向

- **WHEN** 构造 MemoryAgent
- **THEN** 默认 system_prompt MUST 指示 LLM 通过工具探索记忆图、自主决定导航（而非单次查询）

---

### Requirement: FastAPI 对话后端

`create_app(agent)` SHALL 提供对话后端：`POST /chat`（`{message}` → `{reply}`）、`GET /health`（`{ok: true}`）、CORS 中间件、静态前端挂载。

#### Scenario: 可注入任意 agent

- **WHEN** 调用 `create_app(fake_agent)`，其中 fake_agent 暴露 `chat(str) -> str`
- **THEN** `/chat` MUST 转发到 `fake_agent.chat` 并返回其结果

#### Scenario: 缺字段请求被拒

- **WHEN** POST `/chat` 未提供 `message` 字段
- **THEN** MUST 返回 422

#### Scenario: agent 异常返回 500

- **WHEN** agent.chat 抛异常
- **THEN** MUST 返回 500，不重抛给测试客户端

#### Scenario: 根路径服务前端

- **WHEN** GET `/`
- **THEN** MUST 返回 `index.html`（content-type 含 text/html）

---

### Requirement: 环境变量构建生产 agent

`build_agent_from_env()` SHALL 从 `MCS_CONFIG`（yaml 路径）、`AGENT_LLM_API_KEY`、`AGENT_LLM_MODEL`、（可选）`AGENT_LLM_BASE_URL` 构建生产 `MemoryAgent`；缺关键变量时以非零码早失败。

#### Scenario: 缺 MCS_CONFIG 早失败

- **WHEN** 未设 `MCS_CONFIG`
- **THEN** MUST 抛 `SystemExit`（非零）

#### Scenario: 缺 API key 早失败

- **WHEN** 设了 `MCS_CONFIG` 但未设 `AGENT_LLM_API_KEY`
- **THEN** MUST 抛 `SystemExit`（非零）

---

### Requirement: 启动入口

`python -m mcs_agent` SHALL 构建生产 agent 并启动 uvicorn（默认 127.0.0.1:8000）。

#### Scenario: 模块入口可启动

- **WHEN** 执行 `python -m mcs_agent`
- **THEN** MUST 调用 `app.run()`（uvicorn 惰性 import）

---

### Requirement: 导航交给大模型

记忆 agent 的导航决策 SHALL 由 LLM 主导：LLM 经工具组合探索记忆图（search 找入口 → associate 联想扩展 → reason 找路径），而非单次粗粒度查询。

#### Scenario: 多步导航

- **WHEN** 用户提问需多步探索
- **THEN** LLM MAY 在一轮 chat 内连续调用 search → associate → reason
- **AND** 前序工具返回的节点 id MUST 可被后序工具参数引用

---

### Requirement: 工具返回携带节点 id

`search` / `associate` / `find_path` 的返回文本 SHALL 包含节点 id，使 LLM 能在后续工具调用中引用具体节点。

#### Scenario: 返回含 id

- **WHEN** search / associate / find_path 返回节点
- **THEN** 文本 MUST 含可被 LLM 提取的节点 id（如 `[id:...]`）

---

### Requirement: learn 原语（写入）

`MemoryStore.learn(text)` SHALL 封装 MCS 写管线 `ingest`，返回写入状态摘要。

#### Scenario: learn 即 ingest

- **WHEN** 调用 `learn(text)`
- **THEN** MUST 在 worker 线程执行 `mcs.ingest(text)` 并返回状态摘要

---

### Requirement: search 原语（种子搜索）

`MemoryStore.search(query, mode)` SHALL 按 mode 返回种子节点候选：

- `keyword`：经 EntryPlugin 链（jieba 切词 + 字面匹配）定位
- `direct`：返回虚拟根 `__seed_root__` 的层级子节点（顶层 hub），按预算截断
- `vector`：未实现，返回"未实现"提示

#### Scenario: keyword 模式

- **WHEN** `search(query, "keyword")`
- **THEN** MUST 返回种子定位结果（含 id）

#### Scenario: direct 模式

- **WHEN** `search(query, "direct")`
- **THEN** MUST 返回 `__seed_root__` 的层级子节点（含 id）

#### Scenario: vector 模式未实现

- **WHEN** `search(query, "vector")`
- **THEN** MUST 返回"未实现"提示文本，MUST NOT 伪造结果

---

### Requirement: associate 原语（联想扩展）

`MemoryStore.associate(seed_id, mode)` SHALL 从指定种子做 BFS 扩展：

- `mcs`：经 `mcs.query(existing_context=[seed])` 复用 MCS 事实 BFS
- `hot` / `random`：未实现，返回"未实现"提示

#### Scenario: mcs 模式

- **WHEN** `associate(seed_id, "mcs")`
- **THEN** MUST 取 seed 节点后经 `mcs.query(existing_context=[node])` 扩展

#### Scenario: hot/random 未实现

- **WHEN** `associate(seed_id, "hot")` 或 `"random"`
- **THEN** MUST 返回"未实现"提示文本

#### Scenario: seed_id 不存在

- **WHEN** seed_id 在图中不存在
- **THEN** MUST 返回错误提示，MUST NOT 抛异常中断

---

### Requirement: find_path 原语（路径搜索）

`MemoryStore.find_path(source_id, target_id)` SHALL 经双向 BFS 在两节点间找最短连通路径，设最大跳数上限；不连通或节点不存在时返回"未找到"文本，不抛异常。

#### Scenario: 连通路径

- **WHEN** 两节点在 max_hops 内连通
- **THEN** MUST 返回路径节点序列（含 id）

#### Scenario: 不连通

- **WHEN** 两节点在 max_hops 内不连通
- **THEN** MUST 返回"未找到路径"文本，MUST NOT 抛异常

#### Scenario: 节点不存在

- **WHEN** source_id 或 target_id 不存在
- **THEN** MUST 返回"节点不存在"文本，MUST NOT 抛异常

---

### Requirement: recall 原语（热点回忆）

`MemoryStore.recall(limit)` SHALL 返回热点事件；当前底座无事件节点与热点排序，返回"未实现"提示，不伪造。

#### Scenario: recall 未实现

- **WHEN** 调用 `recall(limit)`
- **THEN** MUST 返回"未实现"提示文本，MUST NOT 伪造结果

---

### Requirement: QueryEngine.locate_seeds 公共薄方法

`QueryEngine` SHALL 提供公共方法 `locate_seeds(query) -> list[Node]`，薄封装现有种子定位逻辑，供 MemoryStore.search 复用，不改现有 query 行为。

#### Scenario: locate_seeds 等价内部种子定位

- **WHEN** 调用 `locate_seeds(query)`
- **THEN** 结果 MUST 与现有 `_locate_seeds` 一致
- **AND** 现有 `query()` 行为 MUST NOT 改变

---

### Requirement: agent 独立成顶层包 mcs_agent

记忆 agent 应用 SHALL 作为独立顶层 Python 包 `mcs_agent`（位于项目根，与 `mcs/` 平级），而非 `mcs` 的子包，为将来分开打包做准备。`mcs_agent` 单向依赖 `mcs`（agent 使用 MCS 能力，MCS 核心不依赖 agent）。

#### Scenario: 包路径与 import

- **WHEN** 引用 agent 模块
- **THEN** import 路径 MUST 为 `mcs_agent.*`（如 `mcs_agent.app`、`mcs_agent.loop`）
- **AND** MUST NOT 再从 `mcs.agent.*` 导入

#### Scenario: 对 mcs 的单向依赖

- **WHEN** `mcs_agent` 内部引用 MCS 能力
- **THEN** MAY 从 `mcs.*` 导入（如 `mcs.presets`、`mcs.entities`）
- **AND** `mcs` 核心包 MUST NOT 导入 `mcs_agent`
