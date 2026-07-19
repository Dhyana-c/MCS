## Why

前序 change [`mcs-mem-package-extract`](../../changes/archive/2026-06-28-mcs-mem-package-extract/proposal.md)（2026-06-28）已把记忆应用拆成独立顶层包 `mcs_mem`，但**仍同仓、同 `pyproject`、同发行物**——全仓只有一个 `pyproject.toml`（`name="mcs"`），把 `mcs`/`mcs_agent`/`mcs_mcp`/`mcs_mem` 打成一个发行物。本 change 再向前一步，解决两件事：

1. **发布底层到 PyPI**：让外部能 `pip install` 图引擎。`mcs` 这个分发名在 PyPI **已被他人占用**（`https://pypi.org/pypi/mcs/json` 返回 200），必须换名。
2. **拆 `mcs_mem` 到独立 git repo**：让记忆应用（碎片 / 日记 / 召回 / 看板 / 前端 / 定时调度）独立演进、独立版本、独立前端产品节奏。

**前置调研**（6 agent 多维调研 + 对抗审计，结论见 `design.md` §1）给出关键结论：拆 `mcs_mem` 到独立 repo 有一个**致命前置**——`mcs_agent` 当前不是独立可发行包，`mcs_mem` 拆出后 `pip install` 会因 `dependencies=["mcs_agent"]` 指向不存在的发行物而**装不上**。**因此必须先发布底层、再拆上层**（本 change 两阶段顺序即由此决定）。

**命名决策（名实相符）**：`mem`=memory，记忆应用才像"记忆"。故：
- **图引擎** → PyPI 分发名 **`mcs-core`**（import 名仍 `mcs`，**代码零改动**）。
- **记忆应用产品** → 保留 **`mcs-mem`**（import 名 `mcs_mem`，**不改名**），拆到独立 repo。

**执行时机**：本 change **现在只写 proposal，不立即执行**——产品代码（前端 UI P1/P2、`agent-context-autonomy` 等）尚未稳定，迁移工作宜在边界固化后进行（见 `design.md` §10）。本 proposal 锁定方案与步骤，留待将来执行。

## What Changes

### Phase 1 — 发布底层 `mcs-core` 到 PyPI

- `pyproject.toml`：`name` 由 `mcs` 改为 **`mcs-core`**；`packages.find` 去掉 `"mcs_mem*"`（保留 `"mcs*"`/`"mcs_agent*"`/`"mcs_mcp*"`）；**import 名不变**（`mcs`/`mcs_agent`/`mcs_mcp` 代码零改动）。
- 保留 entry point `mcs-mcp`；视需要补 `mcs-agent`（`mcs_agent.app:run`，执行时确认 `run` 存在）。
- 版本起步 `0.1.0`。
- 本地构建（`build`）→ `twine check` → **TestPyPI 先行验证**（占名 / 版本号不可逆，先试）→ 正式 PyPI。
- **凭证**：PyPI token 经环境变量 `TWINE_PASSWORD`（或 `~/.pypirc`，**加 `.gitignore`、不入库**）传入；**MUST NOT** 硬编码或入库（曾发生 token 明文贴对话，发布前 revoke 重发）。

### Phase 2 — 拆 `mcs_mem` 到独立 repo `mcs-mem`

- 新建 git repo `mcs-mem`（`gh` 已登录，可 `gh repo create`；或网页建）。
- 迁移：`mcs_mem/` 整目录（8 `.py` + `static/` + `prompts/`）+ **7 个** mcs_mem 测试（`test_capture_api` / `test_consolidate_api` / `test_consolidation` / `test_diary` / `test_diary_api` / `test_fragments` / `test_manage_ui`）+ demo（`_run_mem_demo.py` / `mcs_mem_demo*/` + 对应 `.gitignore` 行）。
- **`test_agent_memory.py` 留原仓**（属 `mcs_agent`，非 mcs_mem）。
- 新 repo `pyproject.toml`：`name="mcs-mem"`、`dependencies=["mcs-core>=0.1.0", fastapi, uvicorn, apscheduler, ...]`、entry `mcs-mem = "mcs_mem.app:run"`。
- 原仓清理：删 `mcs_mem/`、删 7 个 mcs_mem 测试、切分 `docs/memory-agent.md`、更新 `README.md` / `CHANGELOG.md`。
- **spec 归属**：`openspec/specs/` 下 5 个 mem 专属 capability（`fragment-capture` / `agent-consolidation` / `consolidation-scheduler` / `diary-generation` / `memory-management-ui`）**随产品 repo 迁走**（产品持有自己的契约），原仓 `openspec/specs/INDEX.md` 删引用。
- **git history**：新仓**从空起步**（不迁历史；跨包 archived change 难干净切割，单作者项目收益低）。
- **真机验证（不 mock）**：新 repo 配真实 `.env` / `mcs.yaml` + LLM key（缺则向用户索取，**不得 mock**）→ `pip install -e .` + `pytest` + 实跑 `/note` / `/consolidate` / `/recall` 通。

### Phase 3（可选，缓做）— 运行时共生解耦

调研指出 3 处运行时硬绑定：`/recall` 直接 `new MemoryAgent`、`register_base_routes` 共享同一 FastAPI app、图库路径继承 `mcs_agent` 的 `MCS_CONFIG`。若仅"代码分两 repo、运行时仍共生"，本阶段可不做；仅当需独立部署（独立端口 / 进程 / 图库）时再做。

## Capabilities

纯**工程 / 发布 / 迁移**——不改核心图模型 capability（4 类节点 / 边模型 / 不变量 / 守门均不动）。`mcs_mem` 的 5 个 capability 端点契约不变，仅**代码归属仓**变更。

执行时若需同步 `project-skeleton` capability（mcs_mem 拆出后原仓目录结构变化），在 `specs/project-skeleton/spec.md` delta 补；是否新增 `package-distribution` capability（记录分发名 / import 名 / 依赖 / entry point 契约）执行时再定。本 proposal 暂不带 `specs/` delta（边界未固化，现在写易过时）。

## Impact

- **`pyproject.toml`（原仓）**：name 改 `mcs-core`、去 `mcs_mem*`、补 entry。
- **新 repo `mcs-mem`**：`pyproject.toml`（name / 依赖 / entry）+ 迁入 `mcs_mem/` + 7 测试 + demo + 5 spec + `docs/memory-agent.md` 的 mcs_mem 节。
- **原仓删除**：`mcs_mem/`、7 测试、demo、5 spec、`docs/memory-agent.md` 的 mcs_mem 节。
- **原仓更新**：`README.md`（加 `pip install mcs-core` + 指向 mcs-mem repo）、`docs/memory-agent.md`（切分）、`openspec/specs/INDEX.md`（删 5 spec 引用）、`CHANGELOG.md`。
- **接口契约（发布后 MUST 稳定）**：`mcs_agent.memory.MemoryStore.ingest_structured(content, timestamp)`、`mcs_agent.app.register_base_routes`、`mcs_agent.loop.MemoryAgent.__init__`（memory / llm / tools / max_turns 关键字）、`mcs_agent.tools.{READONLY_TOOL_NAMES, ToolsetConfig}`——`mcs-mem` 依赖 `mcs-core` 的硬契约，底层演进须保持向后兼容或同步升版。
- **回归**：拆仓后单仓"一次 pytest 覆盖全包"丧失；建议补跨仓 CI（`mcs-core` 变更触发 mcs-mem repo 回归）——列为后续可选，不在本 change 硬性范围。
- **安全**：PyPI token 不入库（环境变量 / `~/.pypirc` + `.gitignore`）。
