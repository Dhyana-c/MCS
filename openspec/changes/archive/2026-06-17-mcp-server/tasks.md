## 1. server 装配与配置（D1）

- [x] 1.1 新增 `mcs/mcp/__init__.py`、`mcs/mcp/server.py`
- [x] 1.2 `main()`：读 `MCS_CONFIG` 环境变量（或 `--config` CLI 参数）→ `MCSConfig.from_file(path)` → `Phase1Builder(config).build()` → 持有 MCS；缺配置 / 文件不存在 / build 失败 MUST 清晰报错并非零退出
- [x] 1.3 进程退出时 `mcs.shutdown()`——**仅当 MCS 已成功 build**（build 失败时 MCS 为 None、跳过 shutdown）；try/finally 守住异常路径

## 2. 串行化执行器 + 线程亲和（D5，正确性硬约束）

- [x] 2.1 单 worker 线程（`ThreadPoolExecutor(max_workers=1)`）：在该线程内 build MCS 并执行全部 MCS 调用；MCS 实例 MUST NOT 被其他线程触碰（SQLite 绑创建线程）。**不靠锁**——单 worker 即串行，锁不保证同线程
- [x] 2.2 异步工具处理器把每次调用 `await` 丢给该 worker（串行、不阻塞 stdio 事件循环）；并发到达的工具调用 MUST 串行执行（ingest 与 query 不交错）
- [x] 2.3 单测：并发提交两次调用，断言串行执行（无交错）；MCS 访问均在同一线程

## 3. query 工具（D2 / D3）

- [x] 3.1 定义 `query(query: str) -> str` 工具（schema + 描述）
- [x] 3.2 结果渲染：`Subgraph` → `ContextRenderer.render_facts(nodes, edges, mode=relation_model)` 文本；postprocess 已返回 `str` 则直接透传（`mcs/mcp/server.py`）
- [x] 3.3 `relation_model` 取自已 build 配置（与 store 同模式）
- [x] 3.4 单测：query 返回 Subgraph → 渲染含节点 / 边文本；query 返回 str → 原样透传

## 4. ingest 工具（D2 / D4）

- [x] 4.1 定义 `ingest(text: str) -> str` 工具（schema + 描述）
- [x] 4.2 从 `WriteContext` 提取状态摘要（`len(changed)` 节点 / `len(concepts)` 概念 / `persisted`）返回；**不报边计数**（`WriteContext` 无边计数字段）；MUST NOT 回原始 `WriteContext`
- [x] 4.3 单测：ingest 后返回含计数的状态串

## 5. 错误隔离（D7）

- [x] 5.1 工具处理器包 try/except：单次调用异常 → 返回 MCP 错误响应（含简明原因），server MUST NOT 崩
- [x] 5.2 单测：工具内部抛异常 → 得到错误响应、server 仍可服务下一次调用

## 6. 打包与传输（D6）

- [x] 6.1 `pyproject.toml` 加 `[project.optional-dependencies] mcp = ["mcp>=1.0", "pyyaml>=6"]`
- [x] 6.2 `pyproject.toml` 加 `[project.scripts] mcs-mcp = "mcs.mcp.server:main"`
- [x] 6.3 server 用 stdio 传输；`mcp` 缺失时 `main()` 报 `pip install mcs[mcp]` 清晰指引
- [x] 6.4 单测：mock `mcp` 缺失 → 报含安装提示的错误

## 7. 文档

- [x] 7.1 `README.md` / `docs/`：`pip install mcs[mcp]`、`MCS_CONFIG` 配置、Claude Desktop（command/args/env）接入示例
- [x] 7.2 须知：工具调用慢（多轮 LLM）、调用串行、配置文件受信（沿用 config-file-loading）

## 8. 测试与回归

- [x] 8.1 集成：写最小 YAML（**无 preset、raw 字段**；mock LLM 经 import-path 作 write_llm / read_llm——**不能用 preset**，因 `knowledge_graph()` 校验 LLM 三选一）→ `from_file` → build → 工具处理函数层面跑通 query / ingest（不依赖真实 MCP 传输）
- [x] 8.2 （可选）传输 smoke：用 MCP SDK 内存 / stdio 传输跑一次 list_tools + call_tool（若 SDK 支持内存传输）
- [x] 8.3 基线回归：`mcp` / `pyyaml` 未安装时，核心库导入与既有测试**不受影响**（MCP 为可选）；全仓 `.venv\Scripts\python.exe -m pytest -q` 全绿
