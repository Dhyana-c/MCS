## 1. Phase 1 — `mcs_mcp/server.py` 重写（核心实现）

### 1.1 顶层 import 切换
- [ ] 1.1.1 删 `import threading` / `from concurrent.futures import ThreadPoolExecutor` / `from typing import TYPE_CHECKING` / `from mcs.presets import Phase1Builder` / `from mcs.rendering import format_ingest_status, render_query_result` / `if TYPE_CHECKING: from mcs.core.mcs import MCS`
- [ ] 1.1.2 保留 `import argparse` / `import logging` / `import os` / `import sys` / `import signal` / `from typing import Any` / `from mcs.entities.config import MCSConfig`
- [ ] 1.1.3 新增 `from mcs_agent.builder import create_agent` / `from mcs_agent.loop import MemoryAgent` / `from mcs_agent.llms import AGENT_LLM_REGISTRY`（反推只用 `AGENT_LLM_REGISTRY`，不 import `PROVIDER_TO_MCS_LLM`）
- [ ] 1.1.4 **MUST NOT** `from mcs_agent.app import ...`（会拉 fastapi）；mcp 包仍惰性 import（`build_fastmcp` / `main` 内）

### 1.2 `_llm_config_from_mcs` 反推函数 + `_McpConfigError`
- [ ] 1.2.1 新增 `_McpConfigError(Exception)`（main 捕获 → stderr + `return 1`）
- [ ] 1.2.2 新增 `_llm_config_from_mcs(mcs_config) -> dict`：扫 `plugin_configs` 的 `*_llm` 键、过滤 `k[:-4] in AGENT_LLM_REGISTRY` 得候选；0 候选 → 报「无 LLM 插件」；>1 候选 → 按 `mcs_config.write_llm`（完整插件名）消歧，`write_llm` 不在候选内 → 报「多 LLM 歧义」列名（design D3 伪码）
- [ ] 1.2.3 字段映射：deepseek/ollama 取 `model`/`api_key`（默认 `""`）/`base_url`；claude 优先 `auth_token`（Bearer）、次选 `api_key`；缺 `model` → 报错
- [ ] 1.2.4 返回 `dict`（`llm_provider`/`llm_model`/`llm_api_key`/`llm_base_url`/`llm_auth_token`/`mcs_config` 透传作逃逸口）

### 1.3 `MCPServer` 重构
- [ ] 1.3.1 删 `_executor` / `_submit` / `_build` / `_do_query` / `_do_ingest` / `_shutdown_mcs` / `_worker_thread_id` / `_mcs` 全部
- [ ] 1.3.2 `__init__(self, config_path)`：`MCSConfig.from_file` → `_llm_config_from_mcs`（早失败）→ `create_agent(**kwargs)` 持 `self._agent: MemoryAgent`
- [ ] 1.3.3 新增类方法 `from_agent(cls, agent: MemoryAgent) -> MCPServer`（测试注入路径，绕过反推；design D8）
- [ ] 1.3.4 `run_query(query)` → `return self._agent.chat(query)`；`run_ingest(text)` → `return self._agent.memory.learn(text)`
- [ ] 1.3.5 `shutdown()`：`self._agent.memory.shutdown()`（告警不抛）；`_agent is None` 时跳过

### 1.4 adapter `_get_client` 加锁（design D7，`mcs_agent/llms/`，治本）
- [ ] 1.4.1 `mcs_agent/llms/openai.py` + `anthropic.py`：`_get_client` 用 `threading.Lock` 保护首次构造（`__init__` 建 `self._client_lock`；`with self._client_lock: if self._client is None: ...; return self._client`）——惠及所有调用方、防 double-init、零行为变化；`CallableAgentLLM` 无 `_get_client` 不改

### 1.5 `build_fastmcp` 改 `asyncio.to_thread` + 更新工具 docstring
- [ ] 1.5.1 `import asyncio`（函数内或顶部均可，保 mcp 惰性 import 风格）
- [ ] 1.5.2 `query` / `ingest` 处理器：`try: return await asyncio.to_thread(server.run_query/run_ingest, ...)` + `except Exception` 产出 `[error] ...` 文本（外壳兜底保留）
- [ ] 1.5.3 更新 `query` / `ingest` 工具 docstring（MCP 客户端可见）：`query` 从「返回相关节点与关系边的可读文本」改为「agent ReAct 多步探索后的自然语言答复（含 `[id:...]`）」；`ingest` 注明走 `agent.memory.learn`

### 1.6 `main` 改造
- [ ] 1.6.1 `_resolve_config_path` 原样保留（`--config`/`MCS_CONFIG`）
- [ ] 1.6.2 注册 `SIGTERM` → `KeyboardInterrupt`（POSIX；Windows `try/except (ValueError, OSError)` no-op）—— design D5
- [ ] 1.6.3 三条早失败保留（缺配置/文件不存在 → 2、mcp 缺失 → 1、build 失败 → 1）；`MCPServer(config_path)` 构造包 `_McpConfigError` 捕获 → stderr + `return 1`
- [ ] 1.6.4 `finally: if server is not None: server.shutdown()`（同步调，保证 SQLite 关闭）

## 2. Phase 2 — `mcs_agent` 构造期资源清理（design D6，核心 bug，2 处）

### 2.1 `mcs_agent/builder.py` — build 步骤 3/4 失败兜底
- [ ] 2.1.1 `build()`：步骤 2 `memory = MemoryStore(build_fn)` 后用 `try/except` 包步骤 3/4，失败时 `try: memory.shutdown() except: logger.warning(...)` 再 `raise`（零行为变化）

### 2.2 `mcs_agent/memory.py` — `MemoryStore.__init__` 的 `_submit(build_fn)` 失败兜底
- [ ] 2.2.1 `__init__`：`self._executor` 建后用 `try/except` 包 `self._mcs = self._submit(build_fn)`，失败时 `self._executor.shutdown(wait=False)` 再 `raise`（build_fn 在 worker 内抛——坏 yaml / 坏 sqlite path，构造失败最高频路径；不调 `mcs.shutdown` 因 MCS 未建成）

### 2.3 全量测试
- [ ] 2.3.1 全量测试确认三处 `mcs_agent` 修复（builder / memory 兜底 + adapter 锁见 1.4）成功路径不触发、失败路径多了确定性清理；adapter 锁用并发首查测试验无 double-init

## 3. Phase 3 — `tests/test_mcp_server.py` 重写

### 3.1 A 类：mcs_mcp 层单测（agent 作 collaborator 替身）
- [ ] 3.1.1 实现 `FakeMemoryAgent`（`chat`/`memory.learn`/`memory.shutdown`，可脚本化返回 / 抛异常）
- [ ] 3.1.2 `test_run_query_delegates_to_agent_chat`：`from_agent(fake)` 注入、`fake.chat` 返固定串、断言 `out == reply`（逐字透传、不再断言节点名）
- [ ] 3.1.3 `test_run_ingest_delegates_to_memory_learn`：`fake.memory.learn` 返「已写入 ...」、断言透传
- [ ] 3.1.4 `test_tool_exception_isolated_and_server_survives`：`fake.chat` 抛 `RuntimeError` → 验 `[error] query 失败` + 二次正常调用仍服务
- [ ] 3.1.5 `test_shutdown_calls_memory_shutdown`：验 `agent.memory.shutdown` 被调一次（不是 `agent.shutdown`）

### 3.2 构造期早失败（反推）
- [ ] 3.2.1 `test_no_llm_plugin_early_fail`：YAML 无 `*_llm` → `main` 返 1 + stderr 含提示
- [ ] 3.2.2 `test_unsupported_provider_early_fail`：YAML 配 `glm_llm` → 返 1 含支持集
- [ ] 3.2.3 `test_multiple_llm_ambiguous_early_fail`：YAML 同时 `deepseek_llm`+`claude_llm` 且 `write_llm` 不在候选 → 返 1 提示歧义；`write_llm` 在候选 → 消歧成功

### 3.3 B 类：agent ReAct loop 行为测（走真实 loop，符合不 mock 铁律）
- [ ] 3.3.1 用 `CallableAgentLLM`（`mcs_agent/llms/callable.py`，内置注入适配器）+ `MemoryStore(build_fn=lambda: FakeMCS())` + 真实 `MemoryAgent` 跑 ReAct loop
- [ ] 3.3.2 `test_query_max_turns_forced_fallback`：脚本化 LLM 永返 `tool_calls` → `termination='forced'` 兜底文本（非 error）
- [ ] 3.3.3 `test_query_implicit_termination`：脚本化 LLM 首轮无 `tool_calls` → `termination='implicit'` 直接答复
- [ ] 3.3.4 `test_query_tool_exception_isolated`：脚本化工具抛异常 → `[error]` 隔离、loop 不崩

### 3.4 import 洁净验证
- [ ] 3.4.1 `test_import_mcs_mcp_server_not_pull_fastapi`：隔离子进程 + 阻断 `mcp`/`yaml` + 断言 `fastapi`/`pydantic`/`uvicorn` 不在 `sys.modules`（防误 import `mcs_agent.app`）

## 4. Phase 4 — docs 同步

### 4.1 `docs/mcp-server.md`
- [ ] 4.1.1 §「暴露的工具」表：query 返回列「Subgraph 经 render_facts 渲染」→「agent 多步 ReAct 探索后的自然语言答复文本（含 `[id:...]`）」；ingest 返回列保留 + 注明走 `memory.learn`
- [ ] 4.1.2 §「须知·工具调用慢」：query 改「agent ReAct 多轮探索、多轮 LLM、耗时长」；ingest 改「写图原语不经 agent LLM loop，仅 MCS 写管线抽取阶段用 LLM（比 query 快但仍非瞬时）」——校准「不经 loop」≠「无 LLM」
- [ ] 4.1.3 §「须知·调用串行」：补「串行 + 线程亲和由 `MemoryStore` 单 worker 保证；mcs_mcp 外层仅 `asyncio.to_thread` 不阻塞事件循环，LLM 段可并发」
- [ ] 4.1.4 §「配置」：说明 LLM 复用 MCS yaml（不新增 agent.yaml / `AGENT_LLM_*` env）；YAML 的 `plugin_configs` MUST 含 `{deepseek|ollama|claude}_llm` 之一（否则早失败）；多 LLM 按 `write_llm` 消歧；客户端超时建议 ≥120s

### 4.2 `README.md`
- [ ] 4.2 §「作为 MCP Server」（约 145-165 行）：`pip install -e ".[mcp]"` + `mcs-mcp` 入口 + Claude Desktop json 保留；末尾引语「工具调用慢（多轮 LLM）、调用串行」微调为反映 agent 后端（query 是 agent 多步探索、串行由 `MemoryStore` 单 worker 保证）

## 5. Phase 5 — 验证 + 归档

- [ ] 5.1 grep 确认 `mcs_mcp/server.py` 顶层无 `from mcs_agent.app` / `fastapi` / `import threading` / `ThreadPoolExecutor` / `render_query_result` / `format_ingest_status` / `Phase1Builder`
- [ ] 5.2 `.venv/Scripts/python.exe -m pytest -q` 全绿（含重写的 mcp 测试 + builder 兜底）
- [ ] 5.3 **实机验证（不 mock）**：配真实 `.env` / `mcs.yaml` + LLM key（缺则向用户索取，**不得 mock**）→ `python -m mcs_mcp` 启动 → MCP 客户端调 `query` / `ingest` 通；**分别验 EOF（客户端关闭）/ SIGINT（Ctrl-C）/ SIGTERM（POSIX `kill -15`）三条退出路径后无 `.db-wal` 残留 / `db locked`**（闭合 design D5 shutdown 必达）
- [ ] 5.4 按 OpenSpec 流程 `openspec archive mcp-via-agent`，确认 `openspec/specs/mcp-server/spec.md` 同步更新、docs 一致
