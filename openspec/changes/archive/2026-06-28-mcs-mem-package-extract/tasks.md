## 1. 建 ``mcs_mem`` 包 + 迁移记忆模块

- [x] 1.1 新建 ``mcs_mem/``（与 ``mcs/`` ``mcs_agent/`` 平级）+ ``mcs_mem/static/``
- [x] 1.2 迁移 ``mcs_agent/{fragments,consolidation,scheduler,diary}.py`` → ``mcs_mem/``（内容零改动）
- [x] 1.3 迁移 ``mcs_agent/static/manage.html`` → ``mcs_mem/static/manage.html``
- [x] 1.4 ``mcs_mem/__init__.py``：导出 ``FragmentStore`` / ``Consolidator`` / ``ConsolidationScheduler`` / ``DiaryGenerator`` / ``DiaryStore``

## 2. ``mcs_agent/app.py`` 重构（剥离记忆 + 抽 base routes）

- [x] 2.1 抽 ``register_base_routes(app, agent)``（``/chat`` / ``/health`` / ``/graph/expand``）
- [x] 2.2 ``create_app(agent)`` 仅基础 app（``register_base_routes`` + StaticFiles），删记忆路由 / Consolidator / scheduler lifespan / 记忆 pydantic models / ``fragment_store`` 参数
- [x] 2.3 删记忆相关 import（``consolidation`` / ``diary`` / ``fragments`` / ``scheduler`` / ``READONLY_TOOL_NAMES``）；``mcs_agent`` 不 import ``mcs_mem``（单向）

## 3. ``mcs_mem/app.py`` 新建

- [x] 3.1 ``create_app(agent, fragment_store=None)``：自建 ``FastAPI()`` + Consolidator 早构造
- [x] 3.2 记忆路由（``/note`` / ``/fragments*`` / ``/consolidate*`` / ``/diary*`` / ``/recall``）+ 记忆 pydantic models
- [x] 3.3 ``/manage.html`` 显式 FileResponse 路由（StaticFiles mount **之前**）
- [x] 3.4 调 ``mcs_agent.register_base_routes`` 注册基础路由
- [x] 3.5 scheduler lifespan（随 app 起停）
- [x] 3.6 最后 mount ``mcs_agent/static``（兜底 ``index`` / ``graph``）
- [x] 3.7 ``run``：委托 ``mcs_agent.build_agent_from_env`` + ``mcs_mem.create_app`` + uvicorn

## 4. 打包 / 测试

- [x] 4.1 ``pyproject`` packages.find 加 ``"mcs_mem*"``
- [x] 4.2 测试 import 迁移：``mcs_agent.{fragments,consolidation,scheduler,diary}`` → ``mcs_mem.*``；记忆端点测试用 ``mcs_mem.app.create_app``（``test_agent_app`` 保持 ``mcs_agent.app``）
- [x] 4.3 全量 ``pytest`` 绿（966 passed，零回归）

## 5. 文档

- [x] 5.1 4 个既有 change 的 proposal 顶部加架构修订说明（指向 mcs-mem-package-extract）
- [x] 5.2 ``docs/memory-agent.md``：包结构（mcs_agent 核心 + mcs_mem 记忆应用、单向依赖）+ FastAPI 后端归属 + 启动入口（``python -m mcs_mem``）+ 捕获层归属
- [x] 5.3 ``mcs_mem/__main__.py``：``python -m mcs_mem`` 入口
