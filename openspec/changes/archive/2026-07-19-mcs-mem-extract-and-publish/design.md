# Design — mcs-mem-extract-and-publish

> 本 change 承接 [`mcs-mem-package-extract`](../../changes/archive/2026-06-28-mcs-mem-package-extract/proposal.md)（拆独立顶层包）再向前一步：发布底层到 PyPI + 拆 mcs_mem 到独立 git repo。
> **现在只写 proposal，不执行**——产品边界未固化，迁移宜待稳定后做（§10）。

## 1. 前置调研结论（多 agent 调研 + 对抗审计）

调研覆盖 5 维度（正向依赖 / 反向依赖 / 隐式耦合 / 发布构建 / 自包含度）+ 1 对抗审计。要点：

**代码层面（干净，可拆）**：
- 单向依赖链 `mcs_mem → mcs_agent → mcs`，**零反向 import**（`mcs_agent`/`mcs` 对 `mcs_mem` 仅 docstring 提及，无代码引用）。
- mcs_mem 的 4 个记忆模块（fragments/consolidation/diary/scheduler）全 **Protocol 解耦**、零 mcs_agent import，只在 `mcs_mem/app.py` 单点注入。
- 自带前端（`static/manage.html` app-shell 594 行 + `graph.html` 338 行 + vendor/cytoscape），1807 行独立测试。
- 规模：mcs_mem 8 `.py` / 1646 行；mcs_agent 3402 行；mcs 引擎 13112 行。

**运行时 / 发布层面（5 阻塞，audit 建议 `defer`）**：
1. **致命**：`mcs_agent` 当前不是独立可发行包（全仓单 `pyproject` name=`mcs`）→ mcs_mem 拆出后 `pip install` 失败。**本 change Phase 1 解决。**
2. 全仓 106 commit 单作者、**无 CI** → 拆仓后 `mcs_agent.__init__` 签名变更会**静默**搞坏 mcs_mem 的 recall/confirm。
3. 运行时共生：`/recall` 直接 `new MemoryAgent`、`register_base_routes` 共享同一 FastAPI app、图库路径继承 `mcs_agent` 的 `MCS_CONFIG`。
4. 产品在迭代期（manage.html/graph.html 2026-07、UI P1/P2 待排期）。
5. 宪法级文档（`mcs_mem/__init__.py` docstring + `mcs-mem-package-extract` proposal）已记录一次"刻意不拆独立 app/端口、选逻辑包独立+运行时共生"的决策——本 change 是对其"发布 + 物理分仓"的延伸，**不推翻**其运行时共生立场（Phase 3 缓做）。

## 2. 命名决策（名实相符）

| 层 | import 名 | PyPI 分发名 | 归属仓 |
|---|---|---|---|
| 图引擎核心 | `mcs` | **`mcs-core`** | 原仓（发布） |
| agent loop | `mcs_agent` | （随 `mcs-core`） | 原仓 |
| MCP server | `mcs_mcp` | （随 `mcs-core`） | 原仓 |
| 记忆应用产品 | `mcs_mem` | **`mcs-mem`** | **新 repo** |

理由：`mem`=memory，记忆应用（日记/碎片/召回）才是"记忆"产品；引擎是"图引擎"。把图引擎叫 `mcs-mem` 会误导外部用户（`pip install mcs-mem` 装完发现是图引擎、无记忆功能）。故引擎用 `mcs-core`（核心库）、应用保留 `mcs-mem`（名实相符）。

**import 名全不动**（`import mcs` / `import mcs_mem` 代码零改动），只改 PyPI 分发名——最小改动。

## 3. 发布架构：单发行物 `mcs-core`

选择：**一个 `mcs-core` 发行物**，含 `mcs`+`mcs_agent`+`mcs_mcp` 三个 import 包。

备选：拆成 `mcs-core`/`mcs-agent`/`mcs-mcp` 三个发行物（更"库化"）。**不选**，理由：
- 最小改动（只动 `pyproject` name + `packages.find`）。
- mcs_mem 拆出后只需依赖一个 `mcs-core`，依赖链简单。
- 单作者项目，过度细分发行物增加发版负担，收益低。
- 将来若需细分（如 mcs_mcp 独立），再拆不迟——发行物拆分可增量做。

> 注：单发行物 `mcs-core` 内含 agent，应用 `pip install mcs-core` 后 `import mcs_agent`——语义上 `mcs-core` 是"MCS 核心套件（引擎+agent+mcp）"，可接受。

## 4. 分发名 vs import 名

Python 包两个名字：
- **分发名**（distribution name）：`pyproject` 里的 `name`，`pip install <分发名>` 用。连字符规范（`mcs-core`）。
- **import 名**（import name）：代码里 `import <名>` 用，对应包目录名（`mcs`/`mcs_agent`）。下划线。

两者**可以不同**。本 change：分发名 `mcs-core`，import 名 `mcs`（引擎）/ `mcs_mem`（应用）。setuptools `packages.find` 按目录名定 import 名，故**目录与代码不动**，只改 `pyproject.name`。

## 5. PyPI 发布流程与凭证

```
本地 build → twine check → TestPyPI 先行 → 正式 PyPI
```

**凭证安全（铁律）**：
- PyPI token 经环境变量 `TWINE_PASSWORD` 或 `~/.pypirc` 传入；`~/.pypirc` **加 `.gitignore`、不入库**。
- **MUST NOT** 硬编码 token 到任何文件 / 提交 / 对话。
- 占名 / 版本号在 PyPI **不可逆**（名一占永占、版本号不可重传）→ **TestPyPI 先行验证**再正式发。
- 已发教训：token 曾明文贴对话 → 发布前**先 revoke 旧 token、重发生成新的**，新 token 不再贴对话。

**版本起步**：`mcs-core==0.1.0`（沿用当前 `mcs/__init__.py` 的 `__version__`）。未来底层 breaking change 走 SemVer 升版。

## 6. repo 迁移清单（带 / 留）

| 内容 | 去向 |
|---|---|
| `mcs_mem/`（8 .py + static/ + prompts/） | → 新 repo |
| 7 个 mcs_mem 测试 | → 新 repo |
| `test_agent_memory.py` | **留原仓**（属 mcs_agent） |
| `_run_mem_demo.py` / `mcs_mem_demo*/` + .gitignore 行 | → 新 repo（examples/ 或 scripts/） |
| 5 个 mem spec（fragment-capture / agent-consolidation / consolidation-scheduler / diary-generation / memory-management-ui） | → 新 repo（产品持自己契约） |
| `docs/memory-agent.md` mcs_mem 节 | → 新 repo（切分，mcs_agent 节留原仓） |
| `mcs/` / `mcs_agent/` / `mcs_mcp/` | **留原仓**（打包 mcs-core） |
| `bench/` / `examples/` / `scripts/` | **留原仓**（不依赖 mcs_mem） |
| git history | 新仓**空起步**（不迁；跨包 archived change 难干净切割） |

**未入库项核对**：`_run_mem_demo.py` / `mcs_mem_demo*/` 当前在 `.gitignore`（未入库），迁移时需本地拷贝过去并纳入新仓版本控制。

## 7. 接口契约（发布后 MUST 稳定）

mcs_mem 经 Protocol / 直接 import 依赖 mcs_agent 的以下符号，**发布后底层演进须保持向后兼容**（或同步升版 + mcs_mem 适配）：

| 契约 | 位置 | 用途 |
|---|---|---|
| `MemoryStore.ingest_structured(content, timestamp) -> str` | `mcs_agent/memory.py:261` | confirm_one 唯一写图出口 |
| `register_base_routes(app, agent)` | `mcs_agent/app.py` | mcs_mem 复用 /chat /health /graph/expand |
| `MemoryAgent.__init__(memory, llm, tools, max_turns, ...)` | `mcs_agent/loop.py:110+` | recall 端点直接实例化（硬依赖，非 Protocol） |
| `READONLY_TOOL_NAMES` / `ToolsetConfig` | `mcs_agent/tools.py:484/490` | recall 只读白名单（内部实现细节，最脆弱） |
| `build_agent_from_env()` | `mcs_agent/app.py` | mcs_mem.run 委托构造生产 agent |
| `AgentLLMInterface.chat(messages, tools) -> Any`（含 `.content`） | `mcs_agent` LLM 后端 | DiaryGenerator 调用 |

> 风险点：`READONLY_TOOL_NAMES` / `ToolsetConfig` 在 mcs_agent 内未标注为公共 API，工具注册机制重构会破坏 mcs_mem recall。Phase 3 可考虑提升为显式公共 API。

## 8. 调研前置条件对照（audit conditions）

audit 给出"建议拆仓前满足"的 6 前置，本 change 处置：

| 前置 | 本 change 处置 |
|---|---|
| 1. mcs_agent 独立发行包（必须） | **Phase 1 解决**（发 mcs-core 含 mcs_agent） |
| 2. 双仓 CI（必须） | Phase 3.4 列为可选；执行时建议至少补跨仓回归触发 |
| 3. 明确产品形态诉求（必须） | 用户已决策：完整拆分（发底层 + 拆应用 repo） |
| 4. 运行时三处解耦之一（必须） | **本 change 不做**（运行时共生可接受，§1 立场）；Phase 3 缓做 |
| 5. 第二位维护者（必须） | 外部前提，不在 change 范围；单作者需自评估双仓维护负担 |
| 6. CHANGELOG / spec 迁移（应做） | Phase 2 含（spec 随迁、CHANGELOG 更新） |

> 即本 change 满足前置 1/3/6，2/4 缓做（2 建议补、4 按当前共生立场不做），5 为外部前提。**执行前建议至少补前置 2（CI）**，否则 mcs-core 演进会静默破坏 mcs_mem。

## 9. 风险与缓解

- **回归丧失**：拆仓后单仓一次 pytest 不再覆盖 mcs_mem。缓解：跨仓 CI（Phase 3.4）；或定期手动 `pip install mcs-core==<新版>` 跑 mcs_mem 测试。
- **接口漂移**：§7 契约若被底层 breaking 改动，mcs_mem 静默坏。缓解：契约符号加版本化保证 / SemVer；recall 的 `MemoryAgent` 直接实例化改为注入（Phase 3.1）。
- **token 安全**：曾明文泄露。缓解：§5 铁律（环境变量 / 不入库 / 发布前 revoke 重发）。
- **运行时共生**：Phase 3 缓做意味着拆仓后 mcs_mem 仍需与 mcs_agent 同进程部署（共享 app/图库）。若未来要独立部署，必须先做 Phase 3。
- **TestPyPI 不可逆**：占名 / 版本号。缓解：严格 TestPyPI 先行。
- **mcs 名被占**：已确认 `mcs` 在 PyPI 被占 → 必须用 `mcs-core`（本 change 已定）。

## 10. 为什么现在写 proposal、不立即执行

用户明确："代码很多地方还没做完，生成 proposal，需要的时候来做。"具体未固化点：

- 前端 UI：`manage.html` app-shell P0 落地，**P1/P2 待排期**（若 P1 加深与 `/graph/expand` 的耦合，会动迁仓边界）。
- ~~`agent-context-autonomy` change~~ **已归档**（2026-07-18，`archive/2026-07-18-agent-context-autonomy`）——`MemoryAgent.__init__` 签名（含 `context_budget` / `fold_after_turns` 等新参数）已稳定，§7 契约基础已固化（此条不再阻塞）。
- `docs/memory-agent.md` 尚在写（git status 显示 `M`、未定稿）。

**触发执行的信号**：① 前端 UI P1/P2 收敛、边界稳定；② ~~`agent-context-autonomy` 归档~~ **已满足**（2026-07-18，`MemoryAgent` 签名稳定）；③ `docs/memory-agent.md` 定稿可切分。①③ 满足后从 tasks.md §1 起按序执行。

## 11. 与前序 change 的关系

- [`mcs-mem-package-extract`](../../changes/archive/2026-06-28-mcs-mem-package-extract/proposal.md)（2026-06-28，已归档）：拆 mcs_mem 成**独立顶层包**（仍同仓同发布）。本 change 在其基础上：发布底层 + 拆**独立 repo**。
- 本 change **不推翻**前序的"运行时共生"立场（仍可同 app/同进程），只做"代码物理分仓 + 底层独立发布"。独立部署是 Phase 3 可选项。
