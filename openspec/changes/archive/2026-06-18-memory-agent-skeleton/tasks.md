## 1. 应用骨架（已完成）

- [x] 1.1 `mcs/agent/memory.py`：MemoryStore 单 worker 线程包装，复用 mcp-server 渲染纯函数
- [x] 1.2 `mcs/agent/loop.py`：MemoryAgent ReAct loop + DEFAULT_SYSTEM_PROMPT + 工具表（memory_query/memory_ingest）+ _dispatch
- [x] 1.3 `mcs/agent/llm.py`：make_openai_llm_call 工厂（openai 惰性 import）
- [x] 1.4 `mcs/agent/app.py`：create_app（/chat /health + CORS + 静态挂载）+ build_agent_from_env + run
- [x] 1.5 `mcs/agent/static/index.html`：聊天前端
- [x] 1.6 `mcs/agent/__main__.py`：`python -m mcs.agent` 入口
- [x] 1.7 `mcs/agent/__init__.py`：导出公共符号

## 2. 测试（已完成）

- [x] 2.1 `tests/test_agent_loop.py`：10 测试（直接答复 / 查询后答复 / 摄取 / max_turns 回退 / 工具异常隔离 / 未知工具 / JSON 错误 / 结果回灌 / MemoryStore 转发）
- [x] 2.2 `tests/test_agent_app.py`：6 测试（health / chat 往返 / 空消息 / 缺字段 422 / 异常 500 / 根路径 index.html）

## 3. 依赖与启动（已完成）

- [x] 3.1 `pyproject.toml` 加 `[agent]` optional 依赖 + dev httpx
- [x] 3.2 验证全量测试通过（568）
