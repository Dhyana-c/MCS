## Context

个人记忆系统 4 片（Slice 1–4）实现时，各片 design D1 决定"走 agent 接缝、代码放
``mcs_agent`` 内、推翻独立 ``mcs_mem`` 包"——理由是"记忆系统走 agent、一个 app 一个端口"。

本 change 推翻"代码放 ``mcs_agent`` 内"部分（**不**推翻"挂同一 app"）：

- ``mcs_mem`` 作为独立顶层包，依赖 ``mcs_agent``
- 运行时仍挂**同一** FastAPI app（``mcs_mem.create_app`` 组装基础 + 记忆路由）
- **不**回到旧"独立 app / 独立端口"

现有约束（已核实）：
- ``mcs_agent`` 核心库（``loop`` / ``memory`` / ``tools`` / ``builder`` / ``llms`` / ``trace``）
  不依赖 ``app``；``app.py`` 是唯一把记忆路由与基础路由混合处。
- 记忆模块（``fragments`` / ``consolidation`` / ``scheduler`` / ``diary``）均用 Protocol
  解耦（``_MemoryStoreProto`` / ``_FragmentStoreProto`` / ``_LLMProto``），**不直接 import
  ``mcs_agent``**——迁移内容零改动。

## Goals / Non-Goals

**Goals:**
1. ``mcs_mem`` 独立包、单向依赖 ``mcs_agent``（破循环）
2. 迁移记忆模块 + app 拆分，行为不变、测试全绿
3. ``mcs_agent`` 退为基础库 + 基础 app（可独立跑 ``/chat`` 等）

**Non-Goals:**
- 不回到独立 app / 独立端口（仍挂同一 app）
- 不改 capability 的行为契约（端点 / 原语语义不变）
- 不拆 ``mcs_agent`` 核心库（loop / memory / tools 等留 ``mcs_agent``）

## Decisions

### D1: 单向依赖 ``mcs_mem`` → ``mcs_agent`` → ``mcs``（破循环）

若 ``mcs_agent/app.py`` 去 ``include`` ``mcs_mem`` 路由 → ``mcs_agent`` import ``mcs_mem``，
而 ``mcs_mem`` import ``mcs_agent`` → **循环依赖**。

**破法**：app 组装在**高层** ``mcs_mem``。``mcs_agent`` 提供可复用件（``register_base_routes``），
``mcs_mem`` 调用它注册基础路由；``mcs_agent`` 全程不 import ``mcs_mem``。单向、无环。

### D2: app 拆分——``register_base_routes`` 复用 + ``mcs_mem.create_app`` 自建

- ``mcs_agent/app.py``：``register_base_routes(app, agent)`` 注册 ``/chat`` / ``/health`` /
  ``/graph/expand``；``create_app(agent)`` 调它 + mount StaticFiles（基础 app）。
- ``mcs_mem/app.py``：``create_app(agent, fragment_store)`` 自建 ``FastAPI()`` → 注册记忆路由 +
  ``/manage.html`` → 调 ``register_base_routes`` → scheduler lifespan → 最后 mount StaticFiles。

### D3: StaticFiles mount 顺序——显式 ``/manage.html`` 路由必须在 mount 之前

Starlette 路由按注册顺序匹配；``mount("/", StaticFiles)`` 是 catch-all，会拦截后注册的路由。
故 ``mcs_mem.create_app`` **必须**先注册所有 API 路由（含 ``/manage.html`` FileResponse），
**最后**才 mount StaticFiles（``mcs_agent/static`` 兜底 ``index.html`` / ``graph.html``）。
``mcs_mem`` **不**复用 ``mcs_agent.create_app``（它已 mount StaticFiles、无法在其后加路由）。

### D4: 记忆模块 Protocol 解耦——迁移零改动

``fragments`` / ``consolidation`` / ``scheduler`` / ``diary`` 全部经 Protocol
（``_MemoryStoreProto`` / ``_FragmentStoreProto`` / ``_LLMProto``）声明依赖、**不** import
``mcs_agent``。``app`` 层把 ``agent.memory`` / ``agent.llm`` 注入。故迁移仅换目录、内容不变。

### D5: ``manage.html`` 归属 ``mcs_mem``，``index.html`` / ``graph.html`` 留 ``mcs_agent``

- ``mcs_mem/static/manage.html``（记忆管理看板）——经显式 ``/manage.html`` FileResponse 路由可达。
- ``mcs_agent/static/{index,graph}.html``（聊天 / 图谱）——经 ``mcs_mem.create_app`` 最后 mount
  的 ``mcs_agent/static`` 兜底可达。
- ``mcs_mem`` 经 ``mcs_agent.app.__file__`` 定位 ``mcs_agent/static``（依赖 ``mcs_agent``，单向）。

### D6: 入口——``mcs_mem.run``（记忆应用）+ ``mcs_agent.run``（基础）

- ``mcs_mem.run``：``build_agent_from_env`` + ``mcs_mem.create_app`` + uvicorn（记忆应用完整入口）。
- ``mcs_agent.run``：``build_agent_from_env`` + ``mcs_agent.create_app`` + uvicorn（仅基础 agent）。

## Risks / Trade-offs

- **``mcs_mem`` 挂 ``mcs_agent/static``**：``mcs_mem.create_app`` mount ``mcs_agent/static`` 兜底
  ``index`` / ``graph``——耦合 ``mcs_agent`` 的 static 路径。缓解：经 ``__file__`` 定位（不硬编码）；
  符合单向依赖。
- **``/manage.html`` 显式路由**：未来若加更多 ``mcs_mem`` 静态页，需各自显式路由（StaticFiles
  只挂了 ``mcs_agent/static``）。缓解：当前仅一页；多页时可 mount ``mcs_mem/static`` 到独立前缀。
- **依赖图加深**：``mcs_mem`` → ``mcs_agent`` → ``mcs`` 三层。缓解：单向清晰、各层职责明确。
