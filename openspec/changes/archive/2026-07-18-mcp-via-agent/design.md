# Design — mcp-via-agent

> 把 `mcs_mcp` 的后端从「直接用 MCS 框架管线（`mcs.query` / `mcs.ingest` / `Phase1Builder` / `render_query_result` + 自建单 worker executor）」彻底改成「全部经 `mcs_agent`」。本文记录关键技术决策与 why；动机见 `proposal.md`，需求见 `specs/mcp-server/spec.md` delta。
>
> 设计依据：10-agent workflow 摸排（5 摸排 + 3 视角设计 + 综合 + 对抗审计）。对抗审计的 2 blocker / 5 major / 3 minor 已逐条闭合进下文决策。

## Context

**`mcs_mcp` 现状**（`mcs_mcp/server.py`）：`MCPServer` 直接持有 `MCS` 实例（`Phase1Builder(config).build()`），自建 `ThreadPoolExecutor(max_workers=1)` 身兼三职——串行化工具调用 / MCS-SQLite 线程亲和 / 不阻塞 stdio 事件循环。两个 MCP 工具直接走框架：`query`→`mcs.query`+`render_query_result`、`ingest`→`mcs.ingest`+`format_ingest_status`。`mcp` 包惰性 import（`build_fastmcp` / `main` 内），核心库不因 mcp 受影响。

**`mcs_agent` 现状**（已实现并稳定）：`MemoryAgent`（ReAct loop + 会话上下文预算自治）+ 12 工具 + `MemoryStore`（自带 `ThreadPoolExecutor(max_workers=1)` 单 worker，MCS 构造与全部原语经 `_submit` 串行、同线程）。构造体系：`create_agent(...)` 工厂 / `AgentConfig` / `AgentBuilder.build` / `AgentConfig.from_file` / `build_agent_from_env`。`MemoryStore` 暴露 `learn` / `ingest_structured` / `shutdown` 等；`MemoryAgent.chat(str) -> str` 无状态单问（每次从全新 messages 起，`SessionContext` 是 chat 内 turn 级、不跨调用）。

**约束**：
- 项目铁律「核心代码必须绝对正确」「不得用 mock 的 LLM/agent/数据替代真实组件启动带前端服务」。
- `mcs` 在 PyPI 已被占（见 `mcs-mem-extract-and-publish`），`mcs_mcp` 与 `mcs_agent` 同属 `mcs-core` 发行物。
- 当前无人用 `mcs_mcp`，无需向后兼容——但仍记录破坏性变更供未来追溯。

## Goals / Non-Goals

**Goals**：
- `mcs_mcp` 后端全部经 `mcs_agent`：`query`→`agent.chat`、`ingest`→`agent.memory.learn`。
- LLM 复用 MCS yaml 已配的那套，**零新增配置文件**、不要求 `AGENT_LLM_*` env。
- 串行 + SQLite 线程亲和**收敛到单一保证点**（`MemoryStore` 单 worker），`mcs_mcp` 不再自建 executor。
- shutdown 路径正确（进程退出含异常 / 强制信号都关 SQLite）。
- 核心代码绝对正确：修掉 `AgentBuilder.build` 部分失败泄漏 `MemoryStore` 的既有 bug。

**Non-Goals**：
- 不改核心图模型 / 守门 / 不变量 / 双层 / universe 归属轴。
- 不改 `mcs_agent` 的 ReAct loop / 工具集 / 上下文预算机制（仅 `builder.py` 一处兜底修复）。
- 不在 `mcs_mcp` 开 `context_budget`（MCP 无状态单问、收益有限，见 D10）。
- 不为 `mcs_mcp` 引入多轮会话 / session 概念（MCP 工具天然无状态；多轮记忆需上层自拼历史，本期不做）。
- 不暴露 agent 的 12 原子工具给 MCP 客户端（用户已定「服务端跑 agent」，客户端只见 `query`/`ingest`）。

## Decisions

### D1 — `MCPServer` 持有 `MemoryAgent` 而非 `MCS`

`MCPServer.__init__` 不再 `Phase1Builder(config).build()`，改为 `create_agent(...)` 构造 `MemoryAgent` 并持有。`run_query` / `run_ingest` 委托 agent。

**why over 备选**：
- 备选 A「`MCPServer` 仍持 `MCS`、另持一个 agent」——双持有，`MCS` 被两边访问破坏线程亲和，否决。
- 备选 B「`mcs_mcp` 直接调 `build_agent_from_env`」——它是双源（`MCS_CONFIG` + `AGENT_LLM_*` env），与「复用 MCS yaml 不新增配置」冲突，否决（见 D3）。
- 选 `create_agent(...)` 平铺 kwargs：少一层 `AgentConfig` 组装，且能把 `MCSConfig.from_file` 结果作 `mcs_config=` 透传作逃逸口（命中 `AgentBuilder._build_fn` 的 `mcs_config` 分支，保 yaml 的 `prompt_overrides` / `token_budget` / `shared_plugins` / `sqlite_storage.path` / 自定义插件全部不丢）。**MUST NOT** 走 `create_mcs(llm=..., db_path=...)` 重建分支（会重建 `MCSConfig` 丢这些）。

### D2 — 删自建 executor，收敛到 `MemoryStore` 单 worker + `asyncio.to_thread` 桥

旧 `MCPServer._executor(max_workers=1)` 三职（串行化 / MCS-SQLite 线程亲和 / 不阻塞事件循环）中，切到 agent 后 MCS 实例归 `MemoryStore` 持有、`MCPServer` 不再直接碰 MCS，**前两职自动归零**，唯一保证点收敛到 `MemoryStore._executor`（`max_workers=1`，MCS 构造与全部原语在其 worker 内 `_submit` 串行、同线程）。`mcs_mcp` 只剩「不阻塞 stdio 事件循环」一职 → `asyncio.to_thread`（asyncio 默认线程池）。

**why**：
- `agent.chat` 是同步阻塞（含多轮 LLM），MUST 经 `await asyncio.to_thread(server.run_query, query)` offload，否则卡死 stdio 事件循环。
- **MUST NOT** 再起 `max_workers=1` 包 `agent.chat`：会两层串行（外层按整次 chat 排队 → chat 内工具又进 `MemoryStore` worker 排队），毁掉 LLM 段并发收益、语义混乱。
- **MUST NOT** 复用 `agent.memory._executor` 作外层：私有、破坏封装、会把 LLM HTTP 段塞进单 worker。

**并发正确性证明**（两个 `agent.chat` 并发，分别在外层线程 A、B 跑）：
1. **LLM 段并发**：`OpenAIAgentLLM` / `AnthropicAgentLLM` 的 client 惰性构造后缓存、跨 chat 复用、跨线程共享；openai/anthropic SDK 基于 httpx、连接池线程安全、无 thread-local 状态。A/B 并发调 client 安全。
2. **`MemoryStore` 段串行**：`_submit = executor.submit(fn).result()`，`max_workers=1` 天然 FIFO 排队、无需锁，A/B 的 `memory.search` / `memory.learn` 在 worker 严格排队不交错。
3. **SQLite 无跨线程**：`_submit` 把 fn 投递到 worker 内执行，fn 体内 `store.conn.execute` 永远在 worker 线程，A/B 从不直接碰 conn，`check_same_thread=True` 永不触发。
4. **chat 不在 `MemoryStore` worker 跑**：chat 在调用方线程（A/B）跑 LLM loop，仅调 `memory.<prim>` 时 `_submit` 进 worker；LLM 段（秒级阻塞、重头戏）并发收益完整保留。

### D3 — LLM 复用 MCS yaml 反推（`_llm_config_from_mcs`）

新增私有函数 `_llm_config_from_mcs(mcs_config) -> dict`（返回 `create_agent` 的 `llm_*` kwargs + `mcs_config`），放 `mcs_mcp/server.py` 顶部。**反推函数归属：`mcs_mcp` 私有**（最小改动；未来 `mcs_mem` 或其他消费者需要再提升到 `mcs_agent.builder.LLMConfig.from_mcs_config` 公共契约，本期不做）。

**反推逻辑**（闭合审计 B1 的歧义消解矛盾——`write_llm` 存的是完整插件名 `deepseek_llm` 而非 provider，必须剥后缀）：

```python
def _llm_config_from_mcs(mcs_config: MCSConfig) -> dict:
    pc = mcs_config.plugin_configs
    # 仅认 provider 在 agent 支持集的 *_llm 键（过滤掉 glm_llm/qwen_llm 等不支持者）
    candidates = [k for k in pc if k.endswith("_llm") and k[:-4] in AGENT_LLM_REGISTRY]
    if not candidates:
        raise _McpConfigError(
            "MCS yaml 未配 agent 可用的 LLM 插件；mcs_mcp 需 plugin_configs 含 "
            f"{sorted(AGENT_LLM_REGISTRY)} 之一的 _llm 段（如 deepseek_llm）"
        )
    if len(candidates) == 1:
        key = candidates[0]
    else:
        # 歧义：按 write_llm 消歧。write_llm 是 MCSConfig 主写 LLM（必填、read_llm 可选默认同 write_llm），
        # 是用户最显式指定的 LLM；agent 的 learn 经 MCS 写管线用 write_llm，chat 用同一 LLM 保持写读
        # 一致——故选 write 而非 read 作消歧锚点。write_llm 是完整插件名（如 deepseek_llm），必在 candidates 内才取。
        wl = mcs_config.write_llm
        key = wl if wl in candidates else None
        if key is None:
            raise _McpConfigError(
                f"MCS yaml 配了多个 agent 可用 LLM {candidates}，且 write_llm={wl!r} 不在其中——"
                f"无法判断 agent chat 该用哪个。请把 write_llm 指向 {sorted(AGENT_LLM_REGISTRY)} 之一"
            )
    # 单候选但与 write_llm 不一致（write_llm 指向不支持的 provider，如 write=glm_llm + read=deepseek_llm）：
    # 静默取唯一支持的候选（agent 必须 tool-calling 支持），log warning 提示 agent chat 与 write 管线 LLM 不同
    if mcs_config.write_llm != key:
        logger.warning(
            "agent chat LLM 取 %s（唯一支持的候选），与 write_llm=%s 不同；"
            "agent 需 tool-calling 支持的 provider，write 管线可用其他", key, mcs_config.write_llm,
        )
    provider = key[:-4]
    cfg = pc[key] or {}
    model = cfg.get("model")
    if not model:
        raise _McpConfigError(f"LLM 插件 {key!r} 缺 model 字段")
    base_url = cfg.get("base_url")  # None → builder 用 _PROVIDER_DEFAULT_BASE_URL 补；不硬编码覆盖用户值
    if provider == "claude":
        auth_token = cfg.get("auth_token")          # claude 优先 Bearer
        api_key = "" if auth_token else cfg.get("api_key", "")
    else:  # deepseek / ollama
        auth_token = None
        api_key = cfg.get("api_key", "")            # ollama 标准形状无 api_key → ""，本地无鉴权 OK
    return {
        "llm_provider": provider, "llm_model": model,
        "llm_api_key": api_key, "llm_base_url": base_url, "llm_auth_token": auth_token,
        "mcs_config": mcs_config,                   # 逃逸口透传，保 yaml 全部配置不丢
    }
```

**provider 约束**：精确 `{deepseek, ollama, claude}`（与 `AGENT_LLM_REGISTRY` / `config.py valid_llms` 三方一致；官方 openai 不在其中，MCS 侧也无 openai 插件故不会配出）。

**早失败边界**（在 `mcs_mcp` 入口显式报、转非零退出码，**MUST NOT** 让 `AgentBuilder` 抛裸 `ValueError`、**MUST NOT** 静默取第一个 LLM 防止 silent pick wrong LLM）：
- **无 `*_llm` 插件**（`plugin_configs` 仅 `sqlite_storage` 等）→ 清晰报错 + `return 1`。
- **多 `*_llm` 歧义**（如 `write_llm=ollama_llm` + `read_llm=deepseek_llm`）→ 按 `write_llm` 消歧（理由见伪码注释：write_llm 是必填主写 LLM、agent learn 经写管线对齐）；`write_llm` 不在候选内（指向不支持的 provider + 多个支持候选并存）→ 报错并指引「把 write_llm 指向 agent 支持集之一」+ `return 1`（write/read 分离是合法配置，正确指引是改 write_llm 指向、而非「仅保留一个」）。
- **单候选但与 `write_llm` 不一致**（`write_llm` 指向不支持的 provider 如 `glm_llm`，另有一个支持候选）→ **静默取唯一支持候选**（agent 必须 tool-calling 支持）+ `log warning` 提示 agent chat LLM 与 write 管线 LLM 不同。这是有意行为（候选唯一、无歧义，非 silent pick wrong LLM），但须让用户知晓。
- **缺 model 字段** → 报错 + `return 1`。
- **claude 无 `auth_token`/`api_key` / deepseek `api_key` 空**（`DEEPSEEK_API_KEY` 未设）→ 反推**不早失败**、首次 chat 才 401。与现有 LLM 插件惰性失败风格一致（仅 warn 不强失败，不破坏 builder 不校验 key 非空的既有契约）。

### D4 — 工具契约：`query`→`agent.chat`（破坏性）/ `ingest`→`memory.learn`

**`query`（破坏性语义变更）**：入参 `query: str`、返回 `str`（类型不变；工具名保留、不改名、不暴露 `existing_context` 等高级参数）。旧 `mcs.query`+`render_query_result` → 新 `agent.chat(query)`，返回 agent ReAct 多步探索后的**自然语言答复**（含 `[id:...]` 存根引用，属 agent 会话上下文折叠协议的合法产物、非错误）。**MUST NOT** 在 server 内包装 / 截断 / 再渲染；**MUST NOT** import `mcs.query` / `render_query_result` / `ContextRenderer` / `Phase1Builder`。

**`ingest`（语义保留、实现路径变更）**：入参 `text: str`、返回 `str`。旧 `mcs.ingest`+`format_ingest_status` → 新 `agent.memory.learn(text)`，内部仍 `mcs.ingest`+`format_ingest_status`（渲染纯函数下沉到 `MemoryStore.learn` 委托，文本格式与旧版逐字一致）。**MUST NOT** 在 server 内重复实现 `format_ingest_status`、**MUST NOT** 走 `agent.chat`（不经 agent ReAct loop）。

**关键语义校准**（任务描述易误读）：「不经 LLM loop」准确说是「不经 agent ReAct loop」，但 `MemoryStore.learn` 内部 `mcs.ingest` 走 MCS 写管线、**必触发 LLM 抽取**（抽概念 / 判关系 / 守门聚类都靠 LLM）——这是图入库的本质、无法绕过。行为上 `ingest` 比 `query` 快（无 ReAct 多轮），但**不是无 LLM**。spec 与 docs MUST 区分二者。

**`forced` 兜底文本契约**：`agent.chat` 达 `max_turns` 未收敛时返回中文兜底「（达到最大轮次，未能给出最终答复。）」（`termination='forced'`，非错误）。`mcs_mcp` **原样透传**、不加注（加注破坏 `out == reply` 契约）。spec / docs 明示「query 偶发返回 agent 降级/forced 兜底文本，非错误响应、客户端不应据此重试；增大 `max_turns` 或换支持 tool-calling 的模型可缓解」。

### D5 — shutdown 路径 + 退出信号矩阵（闭合审计 B2）

进程退出（含异常路径）MUST 调 `agent.memory.shutdown()`（**不是** `agent.shutdown`——`MemoryAgent` 无此方法）→ `MemoryStore.shutdown` 在 worker 线程内 `mcs.shutdown`（SQLite 亲和）→ `executor.shutdown(wait=True)`。`main` 同步 finally 块调。

**退出信号矩阵**（`FastMCP.run` 经 `anyio.run` 包裹，需论证 finally 必达）：
- (a) **EOF**（stdio 关闭，Claude Desktop 关进程）→ `run_stdio_async` return → `run` return → `main` finally → shutdown ✅
- (b) **SIGINT**（Ctrl-C）→ `KeyboardInterrupt` → `except: pass` → finally shutdown ✅
- (c) **SIGTERM**（POSIX `kill -15`）→ Python 默认转 `SystemExit` → finally 仍跑，但 `worker.shutdown(wait=True)` 可能被二次信号中断 → **最小缓解**：`main` 注册 `signal.signal(signal.SIGTERM, ...)` 把 SIGTERM 转成 `KeyboardInterrupt` 让 main 优雅走 `except`+finally（Windows 上 `signal.SIGTERM` 有定义、可注册但不会被原生发送——注册用 `try/except (ValueError, OSError)` 包，无害防御）。

**finally 必达论证**：`FastMCP.run` 经 `anyio.run` 包裹，`anyio` 对 `KeyboardInterrupt` / `SystemExit` **不包装**为 `CancelledError`、直接 propagate 出 `run`；EOF 路径 `run_stdio_async` 正常 return。两类路径 unwind 后 `main` 的 `finally: server.shutdown()`（Python `finally` 在 `BaseException` 下也执行）必达。残留风险仅「SIGTERM 后 `worker.shutdown(wait=True)` 被二次信号中断」——tasks 5.3 实机验证三条退出路径后无 `.db-wal` 残留 / `db locked`。

**MUST NOT**：
- 依赖进程自然退出（Python atexit 顺序不可靠、`ThreadPoolExecutor` worker 在 atexit 才 join、SQLite 可能未 close 致 WAL 残留 / `db locked` / 下次启动锁）。
- 在 async 生命周期钩子里 `await` 同步 shutdown 而不 offload（卡事件循环）。

### D6 — 构造期资源泄漏兜底：`builder.build` + `MemoryStore.__init__`（核心代码绝对正确）

走 agent 后 MCS 实例归 `MemoryStore` 持有、其构造在 `MemoryStore` worker 线程内。**两处**构造期失败会泄漏 worker 线程 + executor + SQLite 连接（无引用靠 GC，时机不可控、`check_same_thread` 连接在 worker 线程外 GC 可能抛 `ProgrammingError`、worker 残留至 atexit）：

1. **`AgentBuilder.build` 步骤 3/4 失败**（构造 backend / `MemoryAgent`）：步骤 2 已建 `MemoryStore`（持 MCS + worker）无引用。审计 M3。
2. **`MemoryStore.__init__` 的 `_submit(build_fn)` 失败**（坏 yaml / 坏 sqlite path / build_fn 在 worker 内抛——**恰恰是构造失败最高频的场景**）：executor 和已起 worker 线程无人 shutdown。对 `mcs_agent.app` 等长活调用方是每次失败构造泄一个线程。

两处都是确定性 bug，非「超范围」可豁免（项目铁律「核心代码所有 bug 都要修」）。`mcs_mcp` 拿不到 builder / MemoryStore 内部引用，无法在 mcs_mcp 层补救——**责任唯一落点是 `mcs_agent`**。

**修复**（零行为变化——成功路径不触发、失败路径多了确定性清理）：

```python
# mcs_agent/builder.py — build()
build_fn = self._build_fn(cfg)
memory = MemoryStore(build_fn)                       # 步骤 2
try:
    # 步骤 3 llm_backend + 步骤 4 return MemoryAgent（不变）...
    return MemoryAgent(memory, llm_backend, ...)
except Exception:
    try: memory.shutdown()                           # 兜底：关 MCS + executor
    except Exception: logger.warning("memory shutdown during failed build raised", exc_info=True)
    raise

# mcs_agent/memory.py — __init__
self._executor = ThreadPoolExecutor(max_workers=1, ...)
try:
    self._mcs = self._submit(build_fn)               # build_fn 在 worker 内跑，可能抛
except Exception:
    self._executor.shutdown(wait=False)              # 兜底：放掉 worker + executor
    raise
```

> `MemoryStore.shutdown` 要求 `self._mcs` 已赋值；`__init__` 失败路径 `self._mcs` 未建成，故用 `executor.shutdown(wait=False)`（不调 `mcs.shutdown`）。

### D7 — adapter `_get_client` 加锁（治本，闭合审计 M4）

`OpenAIAgentLLM` / `AnthropicAgentLLM._get_client` 的 `if self._client is None` 无锁，首次并发 chat 可能 double-init client（两线程各见 None 各自构造、后者覆盖前者），丢一个 httpx 连接池——极端情况下被 GC 的 client 关底层 socket 可能影响在用连接。这影响**所有**调用方（`mcs_agent.app` 等），不只 `mcs_mcp`。

**治本修复**（落点 `mcs_agent/llms/{openai, anthropic}.py`，~3 行/文件）——`_get_client` 用 `threading.Lock` 保护首次构造：

```python
def _get_client(self):
    with self._client_lock:                          # __init__ 建 self._client_lock = threading.Lock()
        if self._client is None:
            self._client = self._build_client()
        return self._client
```

零行为变化（锁只串行化首次构造、之后无竞争），惠及所有调用方，不依赖私有方法、不在 `mcs_mcp` 引入预热副作用。`CallableAgentLLM` 无 `_get_client`、无需改。

> 否决「`mcs_mcp` 构造期预热 `_get_client`」方案：只护 `mcs_mcp` 一个实例、依赖私有方法、且把 SDK import 从首次 chat 提前到启动期（openai/anthropic 未装 → 启动失败而非首查失败）——adapter 加锁治本且零副作用，SDK 仍惰性 import、早失败落在「真实使用」处。

### D8 — 测试注入：`MCPServer.from_agent` 类方法（闭合审计 M5）

现状 `tests/test_mcp_server.py` 的 `MOCK_CONFIG` 用 `write_llm: mock_llm`（无 `*_llm` 后缀、provider 不在 agent registry）。重写后反推会早失败、server 构不出来；加 `deepseek_llm` 段又需真 `DEEPSEEK_API_KEY`（违反测试不依赖外部凭证）。

**决策**：新增 `MCPServer.from_agent(agent: MemoryAgent) -> MCPServer` 类方法——生产走 `__init__(config_path)`（反推 + `create_agent`），测试走 `from_agent`（直接注入脚本化 agent，绕过反推）。生产 / 测试路径分离、不污染生产构造签名。备选「`__init__(config_path=None, agent=None)` 必传其一」参数多、语义混，否决。

### D9 — 依赖分层与边界契约（闭合审计 M7）

画清「不经 mcs 框架」的精确边界，避免读者（尤其 `mcs-mem-extract-and-publish` 拆包后跨仓消费者）困惑：

1. **`mcs_mcp` 仅 import `mcs_agent.{builder, loop, llms}`**（`memory` 间接经 `agent.memory`）——公开 API 边界、稳定契约面。
2. **`mcs_agent` 内部 import `mcs.{presets, rendering, core}`**——实现细节，`mcs_mcp` 不传递依赖。
3. **`memory.learn` → `mcs.ingest` + `format_ingest_status`** 是「记忆原语经 `mcs_agent` 封装后内部复用 mcs 写管线」，**非**「`mcs_mcp` 直接碰 mcs」——这正是「agent 层薄封装 + 不重写图引擎」的设计意图，可接受。

故 spec「后端为 mcs_agent」requirement 的 MUST NOT 列表精确为「`mcs_mcp` 不得直接 import `mcs.query` / `mcs.ingest` / `mcs.presets` / `mcs.rendering`」，**非**「调用栈不出现 mcs」。

**前瞻脚注**（不改 `mcs-mem-extract-and-publish`，仅记录）：本 change 使 `mcs_mcp` 依赖 `mcs_agent` 的 `create_agent` / `MemoryAgent.{chat, memory}` / `MemoryStore.{learn, shutdown}` / `AGENT_LLM_REGISTRY`——当前 `mcs_mcp` 与 `mcs_agent` 同 `mcs-core` 发行物、属发行物内部依赖、非跨仓稳定契约。未来若 `mcs_mcp` 拆独立发行物（`mcs-mem-extract-and-publish` §3 已留口子「将来若需细分（如 mcs_mcp 独立），再拆不迟」），这组符号须升格为公共稳定契约、补进该 change §7。

**MUST NOT import `mcs_agent.app`**：`app.py` 顶层 import fastapi / pydantic / uvicorn，会拉重依赖；`mcs_mcp` 是 stdio 不是 HTTP。已核实 `mcs_agent.{builder, loop, memory, llms}` 与 `mcs_agent/__init__` 均不 import `app`，安全。tasks 列显式验证项（隔离子进程 + 阻断 fastapi 验证 `import mcs_mcp.server` 不间接拉 fastapi）。

### D10 — `context_budget` 不开 / `max_turns` 默认 / 其他

- **`context_budget` 不开**：MCP 工具天然无状态、每次 `query` 独立 chat，`context_budget` 主要价值在多轮、对一次性 query 收益有限；且 `AgentConfig` / `create_agent` 链路不传 `context_budget`（builder.build 调 `MemoryAgent` 时省略、默认 `None`=关闭）。未来若开须绕过 builder 直接 `MemoryAgent(..., context_budget=N)`，本期不做。
- **`max_turns` 保持 `create_agent` 默认 8**：不在 `mcs_mcp` 层覆盖。docs 提示「`query` 最坏 N 轮 × LLM 延迟，建议 MCP 客户端超时设 ≥120s」；用户若需调可在 yaml 透传（未来 `AgentConfig` 支持）。
- **不 mock 铁律两类测试边界**（闭合审计 minor）：
  - **A 类**（mcs_mcp 自身的透传 / 异常隔离 / 早失败单测）：用 `FakeMemoryAgent`（agent 替身）——此时 mcs_mcp 是被测对象、agent 是 collaborator，用替身合理、**不算**「用 mock 启动带前端服务」（mcs_mcp 是 stdio 无前端、测试是单测）。
  - **B 类**（agent ReAct loop 行为测：max_turns 兜底 / 降级 / 异常隔离）：**必须**用 `CallableAgentLLM`（`mcs_agent/llms/callable.py`，项目内置注入适配器、非外部 mock）+ 真实 `MemoryStore` + `FakeMCS`（只替图存储、agent loop 真实跑），符合铁律。

## Risks / Trade-offs

- **[构造期 build 失败资源泄漏]** → D6 修复（builder try/finally 兜底 `memory.shutdown()`）。
- **[SIGTERM 下 shutdown 可能被二次信号中断]** → D5 注册 SIGTERM→KeyboardInterrupt；`MemoryStore.shutdown` 的 `executor.shutdown(wait=True)` 在极端二次信号下仍可能未完成，但已大幅降低概率，记为残留。
- **[double-init client 连接池泄漏]** → D7 adapter `_get_client` 加 `threading.Lock`（治本、惠及所有调用方）；`CallableAgentLLM` 无 `_get_client` 不改。
- **[query 返回 agent 自由文本，破坏结构化客户端]** → 当前无人用；spec / docs 记录 migration note。
- **[LLM 不支持 tool-calling 的静默降级]** → agent.chat 内 LLM 不返 `tool_calls` 时首轮终结（`termination='implicit'`），query 退化成「LLM 单轮直答」（无图检索），是降级非错误。docs 提示用户选支持 function-calling 的模型（deepseek-chat / claude-3-5-sonnet 等支持）。
- **[`max_turns=8` 默认对 MCP 单问偏大]** → 最坏分钟级 query 可能被 MCP 客户端超时杀掉；docs 提示客户端超时 ≥120s，用户可调。
- **[`agent.chat` 无状态单问]** → 不跨 MCP 调用保会话状态；多轮记忆需上层自拼历史（mcs_agent 不提供多轮 chat API），本期不解决、docs 说明。
- **[`MOCK_CONFIG` 反推失败]** → D8 `from_agent` 测试注入绕过。

## Migration Plan

- **破坏性**：`query` 返回值从结构化节点/边渲染文本 → agent 自然语言答复。当前无人用 `mcs_mcp`，无需平滑迁移；spec / docs / 本 design 记录供未来追溯。
- **配置**：YAML 的 `plugin_configs` MUST 含 `{deepseek|ollama|claude}_llm` 之一段——已配 MCS LLM 的 yaml 自然满足，无需用户改配置。
- **回滚**：纯代码层重写 + 一处 builder 兜底修复，git revert 即可；无数据迁移、无不可逆操作。

## Open Questions

设计阶段已闭合全部审计 blocker / major。残留实现期核实项（不阻塞）：
- D7 adapter 加锁：`_get_client` 加 `threading.Lock` 后，确认 `OpenAIAgentLLM` / `AnthropicAgentLLM` 的 `__init__` 建 `self._client_lock` 不破坏现有构造（零行为变化，全量测试验）；`CallableAgentLLM` 无 `_get_client` 不受影响。
- D6 builder 修复是否影响其他 `AgentBuilder.build` 调用方——零行为变化（成功路径不触发），全量测试验证。
