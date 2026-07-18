## 1. Phase 1 — 发布底层 `mcs-core`

### 1.1 `pyproject.toml` 改名 + 去包
- [ ] 1.1.1 `name` 由 `mcs` 改为 `mcs-core`
- [ ] 1.1.2 `packages.find` 去掉 `"mcs_mem*"`（保留 `"mcs*"`/`"mcs_agent*"`/`"mcs_mcp*"`）
- [ ] 1.1.3 视需要补 entry `mcs-agent = "mcs_agent.app:run"`（执行时确认 `run` 存在）
- [ ] 1.1.4 版本 `0.1.0`；README / license 元信息核对

### 1.2 本地构建验证
- [ ] 1.2.1 `pip install -e .` 重装（刷新 egg-info，确认 `top_level.txt` 不含 `mcs_mem`）
- [ ] 1.2.2 `.venv/Scripts/python.exe -m pytest -q` 全绿（去 mcs_mem 测试后）
- [ ] 1.2.3 `python -m build` 出 sdist + wheel
- [ ] 1.2.4 `twine check dist/*` 过

### 1.3 TestPyPI 先行
- [ ] 1.3.1 注册 PyPI / TestPyPI 账号（若未有）；生成 scoped token（`~/.pypirc` 或 `TWINE_PASSWORD`，**不入库**）
- [ ] 1.3.2 `twine upload --repository testpypi dist/*`
- [ ] 1.3.3 干净 venv：`pip install -i https://test.pypi.org/simple/ mcs-core` → `import mcs, mcs_agent, mcs_mcp` 验证

### 1.4 正式 PyPI
- [ ] 1.4.1 `twine upload dist/*` 发布 `mcs-core==0.1.0`
- [ ] 1.4.2 干净 venv：`pip install mcs-core` → import 验证

## 2. Phase 2 — 拆 `mcs_mem` 到独立 repo `mcs-mem`

### 2.1 建 repo + 迁移
- [ ] 2.1.1 `gh repo create mcs-mem`（`gh` 已登录；或网页建）
- [ ] 2.1.2 迁 `mcs_mem/` 整目录（8 `.py` + `static/` + `prompts/`）
- [ ] 2.1.3 迁 7 个 mcs_mem 测试（`test_capture_api` / `test_consolidate_api` / `test_consolidation` / `test_diary` / `test_diary_api` / `test_fragments` / `test_manage_ui`）——**不含** `test_agent_memory.py`
- [ ] 2.1.4 迁 demo（`_run_mem_demo.py` / `mcs_mem_demo*/` + 对应 `.gitignore` 行）
- [ ] 2.1.5 迁 5 个 mem 专属 spec（`fragment-capture` / `agent-consolidation` / `consolidation-scheduler` / `diary-generation` / `memory-management-ui`）

### 2.2 新 repo `pyproject.toml`
- [ ] 2.2.1 `name="mcs-mem"`、`dependencies=["mcs-core>=0.1.0", fastapi, uvicorn, apscheduler, ...]`
- [ ] 2.2.2 entry `mcs-mem = "mcs_mem.app:run"`
- [ ] 2.2.3 新 repo README / LICENSE / `.gitignore`

### 2.3 原仓清理
- [ ] 2.3.1 删 `mcs_mem/`
- [ ] 2.3.2 删 7 个 mcs_mem 测试
- [ ] 2.3.3 删 demo（`_run_mem_demo.py` / `mcs_mem_demo*/`）+ 对应 `.gitignore` 行
- [ ] 2.3.4 删 5 个 mem spec + 更新 `openspec/specs/INDEX.md`
- [ ] 2.3.5 切分 `docs/memory-agent.md`（mcs_mem 节移走、mcs_agent 节留）
- [ ] 2.3.6 更新 `README.md`（加 `pip install mcs-core` + 指向 mcs-mem repo）+ `CHANGELOG.md`
- [ ] 2.3.7 确认 `pyproject.toml` packages 已不含 `mcs_mem*`（1.1.2 已改）

### 2.4 真机验证（不 mock）
- [ ] 2.4.1 新 repo：`pip install -e .` + `pytest -q` 全绿
- [ ] 2.4.2 配真实 `.env` / `mcs.yaml` + LLM key（缺则向用户索取，**不 mock**）
- [ ] 2.4.3 实跑 `python -m mcs_mem`：`/note` / `/fragments` / `/consolidate` / `/diary` / `/recall` 端点通
- [ ] 2.4.4 原仓：`pip install -e .` + `pytest -q` 全绿（确认无残留 mcs_mem 引用）

## 3. Phase 3（可选）— 运行时共生解耦

> 仅当需独立部署（独立端口 / 进程 / 图库）时执行；否则代码分两 repo、运行时共生即可。

- [ ] 3.1 解 `/recall` 直接 `new MemoryAgent`（改注入只读 agent 实例）
- [ ] 3.2 `register_base_routes` 抽公共 lib，或 mcs-mem 自带精简基础路由
- [ ] 3.3 mcs-mem 自带图库配置面（不再继承 `mcs_agent` 的 `MCS_CONFIG`）
- [ ] 3.4 补跨仓 CI（`mcs-core` 变更触发 mcs-mem repo 回归测试）
