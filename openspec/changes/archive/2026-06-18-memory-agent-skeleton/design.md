## Context

MCS 已具备写入管线（`ingest`）与查询管线（`query`），但无对话入口。本提案建立记忆 agent 应用骨架，复用 MCS 现状底座跑通端到端对话，算法层延后（见 `docs/memory-agent-design.md` 命门）。

### 约束

- MCS 非线程安全；SQLite 连接绑定创建线程。FastAPI 在线程池中处理请求，故 MCS 调用必须序列化到单一线程。
- agent 推理用 LLM 独立于 MCS 的 read_llm（agent 自己的 key/模型），经 openai 兼容 tool calling。
- 测试不得依赖真实 LLM API。

### 利益相关者

- 记忆 agent 用户
- MCS 维护者（应用层不得污染核心）

---

## Goals / Non-Goals

**Goals:**

1. 对话式记忆 agent，用户能查询 / 写入记忆图谱
2. 单线程包装 MCS，规避 SQLite 线程亲和
3. LLM 调用可注入，测试零真实 API 依赖
4. 提供可对话的前端页面

**Non-Goals:**

- 不修改 MCS 关系模型（事实仍为边）
- 不引入置信度动态计算 / Hub 折叠 / 事件节点（命门未验证，延后）
- 不实现记忆工具的细粒度导航（本提案仅 query/ingest 两工具；细粒度工具体系见后续 `memory-agent-navigation` 提案）

---

## Decisions

### Decision 1: 单 worker 线程包装 MCS

**选择：** `ThreadPoolExecutor(max_workers=1)`，MCS 构造与全部调用经 `_submit` 提交到该线程。

**理由：** MCS 非线程安全，SQLite 连接绑创建线程。FastAPI 并发处理请求，若多线程直触 MCS 会崩。单 worker 把所有 MCS 访问序列化。此模式与 mcp-server 一致。

**替代方案：** 给 MCS 加锁 / 改线程安全（动核心，违背最小改动）；每次请求新建 MCS（重建图昂贵）。均不取。

### Decision 2: 复用 mcp-server 渲染纯函数

**选择：** MemoryStore 复用 `mcs.mcp.server._render_query_result` / `_format_ingest_status`。

**理由：** MCP server 已实现 query/ingest 结果到可读文本的渲染。复用避免重复实现、保持两个接口渲染一致。

**权衡：** 这两个是 server 模块的内部（下划线）纯函数。复用内部函数在应用层可接受（同包、无外部耦合）；若未来 mcp-server 重构渲染，需同步。

### Decision 3: LLM 调用抽成可注入 callable

**选择：** `llm_call(messages, tools) -> assistant_dict` 作为构造参数，openai 工厂只是其一种实现。

**理由：** 测试注入脚本化 mock，零真实 API 依赖；生产注入 openai 兼容实现。解耦 loop 与具体 LLM SDK。

### Decision 4: ReAct 经 tool calling，异常隔离

**选择：** LLM 返回 `tool_calls` 时执行工具、结果回灌为 `tool` 消息；无 `tool_calls` 时返回最终答复；达 `max_turns` 回退。单次工具异常隔离为 `[error]` 文本，不中断 loop。

**理由：** tool calling 是 openai/deepseek 等通用模式；异常隔离保证一次工具失败不毁整轮对话。

### Decision 5: create_app 接受任意带 chat() 的对象

**选择：** `_AgentProto(Protocol)` 约束，而非具体 MemoryAgent 类型。

**理由：** FastAPI 层与 agent 实现解耦，测试注入 fake agent。

### Decision 6: 线程职责分离

**选择：** agent 的 `llm_call` 在 FastAPI 请求线程执行；仅 `memory.query`/`ingest` 经 `_submit` 进 MCS worker 线程。

**理由：** agent 推理不占用 MCS worker；MCS 内部 read_llm 在 worker 线程内随 query 执行（预期，query 本就该在 worker 跑）。

---

## Risks / Trade-offs

### Risk 1: 单 worker 线程成吞吐瓶颈

**风险：** 所有 MCS 调用串行，高并发下排队。

**缓解：** 记忆 agent 面向单用户对话，非高并发场景，可接受。后续若需并发再考虑 MCS 线程安全化。

---

## Open Questions

1. agent LLM 与 MCS read_llm 是否共用同一 key？——当前设计独立（各自环境变量），可共用同一 key，仅配置分离。
