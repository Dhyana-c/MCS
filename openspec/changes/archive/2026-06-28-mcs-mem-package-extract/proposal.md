## Why

个人记忆系统（捕获 / 整合 / 日记 / 召回 / 管理看板）此前按 4 片拆分实现，代码直接落在
`mcs_agent/` 下（各片 design D1 决定："走 agent、代码放 mcs_agent 内、推翻独立 mcs_mem 包"）。

但记忆功能是 `mcs_agent` 之上的**应用层**（依赖 agent / MemoryStore / 工具），与 agent
核心库（loop / memory / tools / builder）关注点不同。把它独立成 `mcs_mem` 包——依赖
`mcs_agent`、与 `mcs` / `mcs_agent` 平级——让记忆应用可独立演进、边界清晰，且**不**回到
旧设计的"独立 app / 独立端口"（仍挂同一 FastAPI app、共用 agent）。

依赖方向：``mcs_mem`` → ``mcs_agent`` → ``mcs``（单向，破循环）。

## What Changes

- **新建顶层包 ``mcs_mem/``**（与 ``mcs/``、``mcs_agent/`` 平级）
- **迁移**记忆模块到 ``mcs_mem``（内容零改动——均用 Protocol 解耦、不 import ``mcs_agent``）：
  ``fragments`` / ``consolidation`` / ``scheduler`` / ``diary`` / ``static/manage.html``
- **``mcs_mem/app.py`` 新增** ``create_app(agent, fragment_store)``：自建 FastAPI app →
  注册记忆路由 + ``/manage.html`` → 复用 ``mcs_agent.register_base_routes``（``/chat`` /
  ``/health`` / ``/graph/expand``）→ scheduler lifespan → 最后 mount StaticFiles
- **``mcs_agent/app.py`` 重构**：剥离全部记忆路由（端点 / Consolidator / scheduler lifespan /
  记忆 pydantic models），抽出 ``register_base_routes(app, agent)`` 供 ``mcs_mem`` 复用；
  ``create_app(agent)`` 仅基础 app（``/chat`` / ``/health`` / ``/graph/expand`` + StaticFiles）
- **单向依赖**：``mcs_agent`` MUST NOT import ``mcs_mem``（无循环）
- ``pyproject`` packages.find 加 ``"mcs_mem*"``；全部测试 import 迁移到 ``mcs_mem``
- **修改 4 个既有 change 的 design D1**：把"代码放 mcs_agent 内"改回"独立 ``mcs_mem`` 包"
  （本 change 推翻之）

## Capabilities

无新增 capability、无 spec 级修改——**纯架构重构，行为不变**。4 片 capability
（``fragment-capture`` / ``agent-consolidation`` / ``diary-generation`` / ``memory-management-ui``）
的端点契约、原语行为均不变；仅代码 / 模块归属变更（由本 change 的 design 说明）。

## Impact

- **改 ``mcs_agent/app.py``**：剥离记忆路由 + 抽 ``register_base_routes``
- **新建 ``mcs_mem/``**：``__init__`` / ``fragments`` / ``consolidation`` / ``scheduler`` /
  ``diary`` / ``app`` / ``static/manage.html``
- **依赖**：``mcs_mem`` 单向依赖 ``mcs_agent``（``MemoryAgent`` / ``MemoryStore`` / 工具 /
  ``register_base_routes`` / ``build_agent_from_env``）；``mcs_agent`` 不反向依赖
- **``pyproject``**：packages.find 加 ``mcs_mem*``
- **测试**：记忆端点测试改用 ``mcs_mem.app.create_app``；模块 import 迁 ``mcs_mem``
- **既有 change**：4 片 design D1 同步修订（本 change 推翻）
- **入口**：记忆应用入口 ``mcs_mem.run``；基础 agent app 入口 ``mcs_agent.run``（保留）
