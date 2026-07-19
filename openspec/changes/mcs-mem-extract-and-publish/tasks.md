## 1. Phase 1 — 发布底层 `mcs-core`

### 1.1 `pyproject.toml` 改名 + 去包
- [x] 1.1.1 `name` 由 `mcs` 改为 `mcs-core`
- [x] 1.1.2 `packages.find` 去掉 `"mcs_mem*"`（保留 `"mcs*"`/`"mcs_agent*"`/`"mcs_mcp*"`）
- [x] 1.1.3 视需要补 entry `mcs-agent = "mcs_agent.app:run"`（执行时确认 `run` 存在）
- [x] 1.1.4 版本 `0.1.0`；README / license 元信息核对

### 1.2 本地构建验证
- [x] 1.2.1 `pip install -e .` 重装（刷新 egg-info，确认 `top_level.txt` 不含 `mcs_mem`）
- [x] 1.2.2 `.venv/Scripts/python.exe -m pytest -q` 全绿（去 mcs_mem 测试后）
- [x] 1.2.3 `python -m build` 出 sdist + wheel
- [x] 1.2.4 `twine check dist/*` 过

### 1.3 TestPyPI 先行【执行时决策：跳过】
> 用户在执行时决定跳过 TestPyPI（0.1.0 无用户、blast radius 极小；本地已覆盖 TestPyPI 该抓的构建/元数据问题：`twine check` 过 + fresh venv 从 wheel 装 + 164 测试绿 + wheel 内容核对 + import 全通）。proposal §5 的保守口径据此修订。上传前做了不可省预检：`mcs-core` 在 PyPI 名字未被占（404）。

- [x] 1.3.1 ~~注册 TestPyPI 账号 + token~~ — 跳过（上述决策）
- [x] 1.3.2 ~~`twine upload --repository testpypi dist/*`~~ — 跳过（上述决策）
- [x] 1.3.3 ~~干净 venv 从 TestPyPI 装~~ — 跳过（上述决策）

### 1.4 正式 PyPI
- [x] 1.4.1 `twine upload dist/*` 发布 `mcs-core==0.1.0` — 已发布 https://pypi.org/project/mcs-core/0.1.0/
- [x] 1.4.2 干净 venv：`pip install mcs-core` → import 验证 — 通过（`mcs`/`mcs_agent`/`mcs_mcp` + §7 核心契约 `MemoryAgent`/`MemoryStore`/`READONLY_TOOL_NAMES`/`ToolsetConfig`/entry points；`mcs_agent.app` 的 FastAPI 走 `[agent]` extra，设计不变）

## 2. Phase 2 — 拆 `mcs_mem` 到独立 repo `mcs-mem`

### 2.1 建 repo + 迁移
- [x] 2.1.1 `gh repo create mcs-mem`（private：https://github.com/Dhyana-c/mcs-mem）
- [x] 2.1.2 迁 `mcs_mem/` 整目录（8 `.py` + `static/` + `prompts/`）
- [x] 2.1.3 迁 7 个 mcs_mem 测试（`test_capture_api` / `test_consolidate_api` / `test_consolidation` / `test_diary` / `test_diary_api` / `test_fragments` / `test_manage_ui`）——**不含** `test_agent_memory.py`
- [x] 2.1.4 迁 demo（`_run_mem_demo.py` / `mcs_mem_demo*/` + 对应 `.gitignore` 行）
- [x] 2.1.5 迁 5 个 mem 专属 spec（`fragment-capture` / `agent-consolidation` / `consolidation-scheduler` / `diary-generation` / `memory-management-ui`）

### 2.2 新 repo `pyproject.toml`
- [x] 2.2.1 `name="mcs-mem"`、`dependencies=["mcs-core>=0.1.0", fastapi, uvicorn, apscheduler, ...]`
- [x] 2.2.2 entry `mcs-mem = "mcs_mem.app:run"`
- [x] 2.2.3 新 repo README / LICENSE / `.gitignore`

### 2.3 原仓清理
- [x] 2.3.1 删 `mcs_mem/`
- [x] 2.3.2 删 7 个 mcs_mem 测试
- [x] 2.3.3 删 demo（`_run_mem_demo.py` / `mcs_mem_demo*/`）+ 对应 `.gitignore` 行
- [x] 2.3.4 删 5 个 mem spec（注：原仓 `openspec/specs/INDEX.md` 实际未列这 5 spec，"更新 INDEX" 为 no-op；新仓已建自己的 INDEX）
- [x] 2.3.5 切分 `docs/memory-agent.md`（mcs_mem 节移走、mcs_agent 节留；含开篇分层段、FastAPI 路由表、启动命令的 mcs_mem 引用全清）
- [x] 2.3.6 更新 `README.md`（加 `pip install mcs-core` + 指向 mcs-mem repo）+ `CHANGELOG.md`（2026-07-19 条目）
- [x] 2.3.7 确认 `pyproject.toml` packages 已不含 `mcs_mem*`（1.1.2 已改；2.3 顺带清掉 exclude 残留 + `mcs_agent/app.py` docstring 的 mcs_mem 引用统一指向 mcs-mem repo）

### 2.4 真机验证（不 mock）
- [x] 2.4.1 新 repo：`pip install -e .` + `pytest -q` 全绿（fresh venv 从本地 mcs-core wheel 装，164 passed）
- [ ] 2.4.2 配真实 `.env` / `mcs.yaml` + LLM key（缺则向用户索取，**不 mock**）— **DEFERRED：用户决策推迟**（产品 WIP，164 测试已覆盖功能契约；实跑 python -m mcs_mem 的端点冒烟待产品稳定后做）
- [ ] 2.4.3 实跑 `python -m mcs_mem`：`/note` / `/fragments` / `/consolidate` / `/diary` / `/recall` 端点通 — **DEFERRED：依赖 2.4.2**
- [x] 2.4.4 原仓：`pip install -e .` + `pytest -q` 全绿（1158 passed，确认无残留 mcs_mem 代码引用；剩余 mcs_mem 字样均为 docstring/历史归档/本地 mcs.yaml 注释，非代码）

## 3. Phase 3（可选）— 运行时共生解耦【执行时决策：跳过】

> 用户决策跳过（当前运行时共生即可，无独立部署需求）。仅当需独立端口 / 进程 / 图库时再做。

- [x] 3.1 ~~解 `/recall` 直接 `new MemoryAgent`~~ — 跳过（共生可接受）
- [x] 3.2 ~~`register_base_routes` 抽公共 lib~~ — 跳过
- [x] 3.3 ~~mcs-mem 自带图库配置面~~ — 跳过
- [x] 3.4 ~~补跨仓 CI~~ — 跳过（单作者项目、无 CI 基线；mcs-core 接口演进靠 SemVer + 手动回归）
