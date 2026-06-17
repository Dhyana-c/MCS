## Why

`memory-agent-skeleton` 提案建立了应用骨架，但记忆工具只有 `memory_query` / `memory_ingest` 两个粗粒度工具——LLM 无法控制**如何导航**记忆图：不能选择入口模式（关键词 / 直接拿根的高层节点 / 向量）、不能从某种子出发联想扩展、不能在两个节点间找路径、不能回顾热点。

记忆 agent 的核心价值在于**让大模型主导导航**：由 LLM 决定查什么、用哪个种子、用哪种扩展模式、选哪两个节点找路径。这要求把 MCS 查询管线的阶段（种子定位、BFS 扩展）拆成独立工具，把细粒度控制权交给 LLM。

此外，agent 作为应用层应与 MCS 核心解耦、独立成包，为将来分开打包做准备。

## What Changes

### 工具体系重构（5 工具，导航交给 LLM）

用以下 5 个工具替换原 `memory_query` / `memory_ingest`，工具是 MCS 插件/引擎能力的薄封装，LLM 负责选工具与参数：

- **`learn(text)`**：写入。封装 MCS 写管线 `ingest`。
- **`search(query, mode)`**：种子搜索。`mode`:
  - `keyword`：jieba 切词 + 字面匹配（复用现有 EntryPlugin 链）
  - `direct`：返回虚拟根 `__seed_root__` 下的高层节点（hub 子图）作为候选
  - `vector`：向量检索（**未实现**，诚实返回"未实现"）
- **`associate(seed_id, mode)`**：从指定种子做 BFS 联想扩展。`mode`:
  - `mcs`：复用 MCS 事实 BFS（`mcs.query(existing_context=[seed])`）
  - `hot`：热点排序扩展（**未实现**，priority Phase1 默认 0.0）
  - `random`：随机截断扩展（**未实现**）
- **`reason(source_id, target_id)`**：在两节点间找连通路径（双向 BFS，允许失败，不连通返回空）。MCS 当前无路径搜索，需新增。
- **`recall(limit)`**：返回热点事件（**未实现**，依赖事件节点 + priority）。

### 包独立化（结构变更）

agent 从 `mcs/agent/`（mcs 子包）移到顶层 `mcs_agent/`（项目根，与 `mcs/` 平级），成为独立 Python 包：

- 所有 import `mcs.agent.*` → `mcs_agent.*`；启动入口 `python -m mcs.agent` → `python -m mcs_agent`。
- `mcs_agent` 单向依赖 `mcs`（agent 使用 MCS 能力，MCS 核心不依赖 agent）。
- 单 `pyproject.toml` 保留，`[agent]` optional deps 跟随；独立 pyproject 留待将来真要分开打包时再加（本期不做）。

### 设计要点

- **多步状态传递**：每个工具返回文本中**带节点 id**，LLM 下一步把 id 传给 `associate`/`reason`。
- **空壳诚实**：未实现的 mode / 工具返回 `[未实现] ...`，且工具 `description` 标明可用 mode，避免 LLM 浪费轮次。
- **MCS 核心不动**（最小改动）：联想复用公共 API `mcs.query(existing_context=[seed])`；路径搜索在 mcs_agent 层用 store 接口新写；search 复用 QueryEngine 种子定位（经新增公共薄方法 `locate_seeds`，见 design 决策 5）。

## Capabilities

### Modified Capabilities

- `memory-agent`：工具集从 2 个（memory_query/memory_ingest）演进为 5 个导航工具（learn/search/associate/reason/recall）；系统提示词改为"导航交给大模型"；MemoryStore 扩展细粒度原语；**agent 从 mcs 子包独立为顶层包 `mcs_agent`**。

## Impact

### 代码变更

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `mcs/agent/` → `mcs_agent/` | 移动 | 整个包从 mcs 子包移到顶层（git mv 保留历史） |
| `mcs_agent/memory.py` | 修改（移动+改） | MemoryStore 加 learn/search/associate/find_path/recall 原语 + 节点 id 渲染 helper |
| `mcs_agent/loop.py` | 修改（移动+改） | 工具表换 5 工具 + 完整 description；DEFAULT_SYSTEM_PROMPT 改导航导向；_dispatch 分发 5 工具 |
| `mcs_agent/__main__.py` | 修改 | `python -m mcs_agent`（原 mcs.agent） |
| `mcs_agent/__init__.py`、`llm.py`、`app.py`、`static/` | 移动 | 随包迁移，内部 import 改 mcs_agent.* |
| `mcs/core/query_engine.py` | 修改 | 加公共薄方法 `locate_seeds(query)`（决策 5） |
| `tests/test_agent_loop.py` | 修改 | import 改 mcs_agent.*；5 工具分发、多步 id、空壳、边界 |
| `tests/test_agent_memory.py` | 新增 | import mcs_agent.*；MemoryStore 新原语 + 路径搜索边界 |
| `pyproject.toml` | 修改 | `[agent]` deps 指向新包；包发现覆盖 mcs_agent |

### 依赖关系

- `mcs_agent` 单向依赖 `mcs`（用其公共 API：ingest/query/query_engine/store/presets/entities）；`mcs` 核心不反向依赖 agent。
- 联想依赖 MCS 公共 `mcs.query(existing_context=...)`；search 依赖 QueryEngine 种子定位；路径搜索依赖 store 接口。均不改查询语义。
- vector / hot / random / recall 为空壳，不引入新依赖。

### 风险

- **包移动破坏 import**：所有引用 `mcs.agent.*` 处须改 `mcs_agent.*`。缓解：全局搜索替换 + 全量测试验证。
- **导航策略依赖 LLM 质量**：工具多了，LLM 选错风险上升。缓解：description 写清、空壳标明、系统提示词给典型流。
- **direct 根扁平化返回过多**：缓解：direct 结果按 top-N 截断。
- **路径搜索代价**：缓解：max_hops 上限（默认 6）。
