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

### Requirement: MemoryStore 复用共享渲染纯函数

`MemoryStore` SHALL 复用核心库 `mcs.rendering` 的公开纯函数 `render_query_result`（associate）与 `format_ingest_status`（learn）渲染结果，不重复实现。MUST NOT 引用任何应用包（如 `mcs_mcp`）的内部 / 私有函数。

#### Scenario: 复用而非重复实现

- **WHEN** `MemoryStore` 渲染 associate / learn 结果
- **THEN** MUST 调用 `mcs.rendering` 的公开渲染函数
- **AND** MUST NOT 自行实现等价渲染逻辑

#### Scenario: 不跨应用引用私有函数

- **WHEN** 检查 `mcs_agent` 的 import
- **THEN** MUST NOT 出现 `from mcs_mcp...` 或 `from mcs.mcp...` 的渲染函数引用
- **AND** 渲染函数 MUST 来自核心库 `mcs.rendering`

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

`MemoryAgent` SHALL 接受 `AgentLLMInterface`（`chat(messages, tools) -> AssistantMessage`）可注入后端，而非绑定具体 LLM SDK；裸 callable（`llm_call(messages, tools) -> assistant_dict`）经 `CallableAgentLLM` 适配器自动包装，保持既有注入式测试兼容。

#### Scenario: 测试注入裸 callable mock

- **WHEN** 测试构造 `MemoryAgent(memory, scripted_llm_call)`，其中 `scripted_llm_call` 为裸 callable
- **THEN** loop MUST 经 `CallableAgentLLM` 适配使用该 callable，不依赖真实 LLM API

#### Scenario: 注入 AgentLLMInterface 后端

- **WHEN** 注入 `AgentLLMInterface` 子类实例
- **THEN** loop MUST 直接调用其 `chat()`，并把返回的 `AssistantMessage.trace` 计入追踪（替代读取 `assistant_dict["_trace"]`）

### Requirement: 记忆工具集（learn / search / associate / reason / recall）

`MemoryAgent` SHALL 经 `ToolSpec` 注册表（`BUILTIN_TOOLS`）向 LLM 暴露**可配置的**导航工具集，**默认 5 个**（learn / search / associate / reason / recall），分发到 `MemoryStore` 对应原语；工具集经 `ToolsetConfig` 可启用/禁用子集、覆盖参数：

- `learn(text)` → `memory.learn`
- `search(query, mode)` → `memory.search`
- `associate(seed_id, mode)` → `memory.associate`
- `reason(source_id, target_id)` → `memory.find_path`
- `recall(limit)` → `memory.recall`

导航决策权交给 LLM：由 LLM 决定选哪个工具、哪个种子、哪种模式、哪两个节点。

#### Scenario: 默认暴露全部 5 工具

- **WHEN** 构造 agent 时未指定 `ToolsetConfig`（或缺省）
- **THEN** 暴露给 LLM 的工具 schemas MUST 为全部 5 个内置工具（learn / search / associate / reason / recall）

#### Scenario: 分发到 MemoryStore 原语

- **WHEN** LLM 调用任一已启用工具
- **THEN** MUST 经 dispatch 转发到对应 `MemoryStore` 原语（learn / search / associate / find_path / recall）

#### Scenario: 禁用工具不暴露给 LLM

- **WHEN** `ToolsetConfig.enabled` 排除某工具（如禁用 `recall`）
- **THEN** 该工具 MUST NOT 出现在传给 LLM 的 schemas 中
- **AND** LLM 调用该工具名 MUST 返回 `[error] 未知工具：{name}`

#### Scenario: 参数覆盖

- **WHEN** `ToolsetConfig.params` 为某工具指定参数（如 `{"reason": {"max_hops": 8}}`，key = 工具名）
- **THEN** dispatch 执行该工具时 MUST 应用覆盖后的参数（而非内置默认值）
- **AND** `params` 与 LLM 入参同名时 MUST 以 `params` 为准（合并口径 `handler(memory, {**llm_args, **params})`）

#### Scenario: 未知工具

- **WHEN** LLM 调用不在已启用工具表中的工具名
- **THEN** MUST 返回 `[error] 未知工具：{name}`

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

### Requirement: 系统提示词导航导向

`MemoryAgent` 默认 system_prompt SHALL 指导 LLM 在"直接作答"与"工具探索记忆图"间自主判断，而非无条件调用工具：

- **何时直接回答（不调工具）**：闲聊 / 问候 / 身份询问；通用知识、常识、推理、计算、写作等不依赖个人记忆的内容；自身能力足以准确作答时。
- **何时探索记忆图（调工具）**：仅当问题依赖"已记下来的东西"（用户曾 learn 或图里的事实 / 关系）。
- **探索策略**：search 返回空或 associate 无相关时，最多换 1-2 种切入（如 keyword 失败改 direct），仍无果据实说明"记忆里没有"、不臆造。
- **记忆诚实**：对记忆类问题不臆造；**不假装记得本轮之前的对话**（会话历史将由图内事件节点承载，当前为过渡态）。

导航决策权仍交给 LLM：选哪个工具、哪个种子、哪种模式、哪两个节点均由 LLM 决定。

#### Scenario: 直接答路径有引导

- **WHEN** 构造 `MemoryAgent`
- **THEN** 默认 system_prompt MUST 含"何时直接回答（不调工具）"的判断标准
- **AND** MUST 含"记忆诚实 / 不假装记得上文"的过渡态约束

#### Scenario: 探索路径保留

- **WHEN** 默认 system_prompt 指导探索
- **THEN** MUST 保留 5 工具（learn / search / associate / reason / recall）说明与跨工具 id 引用规则

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

`MemoryStore.recall(limit)` SHALL 返回最近发生的事件：扫全图 `node_class=事件` 节点，按 `extensions.event_meta.timestamp` 时间倒排（无 timestamp 者排末尾、`node.id` 作次级键保确定性），**全文渲染**为含节点 id 的 LLM 可读文本（name==content 只写一份、每条附 timestamp）；图中无事件时返回空提示。排序口径为**纯近期时间线**——事件节点无专门「热度」字段，不掺热度加权。截断为**条数 `limit` 与 token 上界 T 双约束**：逐条判定，达 `limit` 条、或「纳入该条后的完整渲染文本」超 `token_budget.T` 即停（先到先停；对完整文本**整体估算**、含 header 与行间换行符，渲染口径 == 估算口径，禁止分段累加单条 estimate）；唯一例外是**最近 1 条无条件全文返回**（即使其单条就超 T）。recall 为只读原语、不经 LLM、不进核心活跃视图、不触发写 / 守门 / 裂变。

#### Scenario: 时间倒排返回最近事件

- **WHEN** 图中存在多个带 `event_meta.timestamp` 的事件节点，调用 `recall(limit)`
- **THEN** MUST 按 `timestamp` 倒序（近期在前）返回，至多 `limit` 条
- **AND** 渲染文本 MUST 含每条事件的节点 id（如 `[id:...]`），可被后续工具引用

#### Scenario: 无 timestamp 排末尾

- **WHEN** 部分事件节点无 `event_meta.timestamp`
- **THEN** 这些事件 MUST 排在有 timestamp 的事件之后（末尾）

#### Scenario: limit 截断

- **WHEN** 事件数超过 `limit`
- **THEN** MUST 仅返回 `limit` 条（最近的那批）

#### Scenario: token 预算截断（不超 T）

- **WHEN** 纳入下一条后的完整渲染文本 token 将超过 `token_budget.T`
- **THEN** MUST 停止纳入更早事件，返回的渲染文本总 token MUST ≤ T
- **AND** 截断 MUST 为 `limit` 与 T 双上界、先到先停

#### Scenario: 单条超 T 至少返回最近 1 条

- **WHEN** 最近一条事件全文渲染就超过 T
- **THEN** MUST 仍完整返回该最近 1 条（全文、不截断正文、不返回空）
- **AND** 其余更早事件 MUST 严格受 T 约束

#### Scenario: 同 timestamp 确定性次序

- **WHEN** 多个事件 `timestamp` 相同
- **THEN** 其相对次序 MUST 确定（不依赖存储遍历顺序），便于测试稳定

#### Scenario: 无事件返回空提示

- **WHEN** 图中无任何 `node_class=事件` 节点
- **THEN** MUST 返回空提示文本，MUST NOT 伪造事件

#### Scenario: 经 worker 线程只读

- **WHEN** 调用 `recall`
- **THEN** MUST 经 `ThreadPoolExecutor(max_workers=1)` 单 worker 线程执行
- **AND** MUST 只读 `store.get_all_nodes()`，MUST NOT 触发写 / 守门 / 裂变

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

---

### Requirement: 图级摘要注入 agent system prompt

`MemoryAgent.chat()` SHALL 在每轮对话开头取最新图级摘要（`MemoryStore.graph_summary()`）并注入 system prompt 的「当前记忆图主题」段，使 LLM 能据图主题判断问题是否可能属于记忆范围。注入前 SHALL 对摘要做 ≤ `GRAPH_SUMMARY_TOKEN_BUDGET` 校验 / 截断（防归纳超标进入上下文）。摘要为空时该段降级为占位（如"(尚未生成)"），路由按其余规则工作。

#### Scenario: 每轮注入最新摘要

- **WHEN** 调用 `chat(msg)` 且图级摘要非空
- **THEN** messages 的 system 内容 MUST 含当前摘要文本

#### Scenario: 空摘要降级

- **WHEN** 图级摘要为空（尚未生成）
- **THEN** system 的主题段 MUST 降级为占位，MUST NOT 抛异常

#### Scenario: 超标摘要截断

- **WHEN** 取得的摘要超 `GRAPH_SUMMARY_TOKEN_BUDGET`
- **THEN** 注入前 MUST 截断至 ≤ 预算

---

### Requirement: MemoryStore.graph_summary 原语

`MemoryStore.graph_summary() -> str` SHALL 经单 worker 线程读图级 meta（`get_graph_meta("graph_summary")`），返回摘要文本；无摘要返回空串。调用方线程 MUST NOT 直接读 store（线程安全铁律，同其他原语）。

#### Scenario: 取摘要

- **WHEN** 图级 meta 含摘要
- **THEN** `graph_summary()` MUST 返回该文本

#### Scenario: 无摘要返回空串

- **WHEN** 图级 meta 无 "graph_summary" key
- **THEN** `graph_summary()` MUST 返回 ""

#### Scenario: 经 worker 线程

- **WHEN** 调用 `graph_summary()`
- **THEN** MUST 经 `ThreadPoolExecutor(max_workers=1)` 执行（同其他原语）

### Requirement: AgentConfig / AgentBuilder / create_agent 构造体系

`mcs_agent` SHALL 提供编程式与 YAML 双路径构造记忆 agent：`AgentConfig` 数据对象、`AgentBuilder(config).build() -> MemoryAgent`、`create_agent(...)` 工厂、`AgentConfig.from_file(path) -> AgentConfig`。`build()` 返回 `MemoryAgent`（**不**返回 FastAPI app；`create_app(agent)` 仍是独立一层）。**统一 LLM**：单一 `LLMConfig`（provider/model/api_key/base_url/auth_token）同时驱动 agent 的 chat LLM 与 MCS 的 write/read LLM（provider 键映射两侧；`auth_token` 仅 claude 用，Bearer 授权）；`mcs_config`（完整 MCSConfig）作逃逸口优先（想给 MCS 配不同 LLM 时）。

#### Scenario: 工厂编程式构建可用 agent

- **WHEN** 调用 `create_agent(db_path=..., llm_provider="deepseek", llm_api_key=..., llm_model=...)`（单一 LLM 配置）
- **THEN** MUST 返回可调 `chat()` 且 `learn`/`associate` 可用的 `MemoryAgent`（agent 与 MCS 共用此 LLM），无需 YAML、无需环境变量

#### Scenario: YAML 构造

- **WHEN** `AgentConfig.from_file("agent.yaml")` 后经 `AgentBuilder(config).build()`
- **THEN** MUST 返回按 YAML 配置构建的 `MemoryAgent`（YAML 承载统一 `llm` 配置）

#### Scenario: builder 产物为 agent 而非 app

- **WHEN** 调用 `AgentBuilder(config).build()`
- **THEN** 返回值 MUST 为 `MemoryAgent` 实例，MUST NOT 为 FastAPI app

#### Scenario: db_path 指向已有图谱

- **WHEN** `create_agent(db_path="existing.db", llm_provider=..., llm_api_key=..., ...)` 指向一个已有数据的 SQLite 图
- **THEN** 构建的 agent 的 `MemoryStore` MUST 加载该 db 的已有图数据（经 `Phase1Builder` + `SQLiteStore`，不重建空图）

#### Scenario: 缺图谱来源早失败

- **WHEN** `AgentConfig` 既无 `mcs_config` 也无 `db_path`
- **THEN** `build()` MUST 抛清晰错误（非静默空图）

#### Scenario: 缺 LLM 早失败

- **WHEN** `AgentConfig` 无 `llm`（不论 `mcs_config` 有无——含"只给 `mcs_config` 不给 `llm`"）
- **THEN** `build()` MUST 抛清晰错误（agent chat 无 LLM 后端；`mcs_config` 的 LLM 无 tool-calling、不能作 agent chat 后端），MUST NOT 静默产出 `chat()` 即崩的 agent

#### Scenario: mcs_config 逃逸口

- **WHEN** 同时给 `llm`（agent 用）与 `mcs_config`（MCS 用，含不同 LLM）
- **THEN** agent chat LLM MUST 取自 `llm`，MCS write/read LLM MUST 取自 `mcs_config`

---

### Requirement: AgentLLMInterface 可插拔 LLM 后端

`mcs_agent` SHALL 提供 `AgentLLMInterface` ABC（`chat(messages, tools) -> AssistantMessage`）+ **provider 键**注册表 `AGENT_LLM_REGISTRY`，按 `LLMConfig.provider` 选择后端；同一 provider 键同时映射 MCS 插件（`PROVIDER_TO_MCS_LLM`），实现统一 LLM 配置。**统一 provider 集 = agent adapter ∩ MCS 插件 = `{deepseek, ollama, claude}`**；官方 openai 无 MCS 插件、不作统一 provider 键。`AssistantMessage` 含 `content` / `tool_calls` / `trace`（一等 trace，替代 dict `_trace` 键 hack）。内置 `OpenAIAgentLLM`（openai 兼容，覆盖 deepseek / ollama）与 `AnthropicAgentLLM`（原生 claude；`LLMConfig.auth_token` 支持 Bearer 授权，agent 侧与 MCS `claude_llm` 同源种入）。内部消息 / 工具格式以 openai chat-completions 为 lingua franca。

#### Scenario: 选 deepseek / ollama（openai 兼容）

- **WHEN** `llm.provider="deepseek"` 或 `"ollama"`
- **THEN** MUST 用 `OpenAIAgentLLM`（按 provider 默认 base_url），`chat()` 返回含 `content` / `tool_calls` / `trace` 的 `AssistantMessage`
- **AND** 同一 provider MUST 经 `PROVIDER_TO_MCS_LLM` 映射到对应 MCS 插件（deepseek / ollama）

#### Scenario: 选 claude（anthropic 原生）

- **WHEN** `llm.provider="claude"`
- **THEN** MUST 用 `AnthropicAgentLLM`（原生 claude）
- **AND** 未安装 `anthropic` 依赖时 MUST 抛清晰错误（不影响 openai-compat 后端可用性）

#### Scenario: claude 用 auth_token（Bearer）

- **WHEN** `llm.provider="claude"` 且给 `llm.auth_token`
- **THEN** agent 侧 `AnthropicAgentLLM` MUST 用 `auth_token`（Bearer）授权
- **AND** MCS 侧 `claude_llm` 插件配置 MUST 同时种入 `auth_token`（claude_llm `auth_token` 优先于 `api_key`）

#### Scenario: trace 为一等字段

- **WHEN** 任一后端 `chat()` 返回
- **THEN** `AssistantMessage.trace` MUST 含 token 用量 / 延迟 / 工具名（`LLMCallTrace`），MUST NOT 依赖 dict `_trace` 键

#### Scenario: 未知 provider 早失败

- **WHEN** `llm.provider` 不在 `AGENT_LLM_REGISTRY`
- **THEN** 构建时 MUST 抛清晰错误，不静默回退

