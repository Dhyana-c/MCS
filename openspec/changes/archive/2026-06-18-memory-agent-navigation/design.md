## Context

`memory-agent-skeleton` 建立的 agent 仅有 memory_query/memory_ingest 两工具，LLM 无法控制导航。本提案把 MCS 查询管线的阶段拆成独立工具，把导航决策权交给 LLM。

MCS 查询管线现状（见 query-pipeline spec）：①前置 → ②种子定位（EntryPlugin 链 + Trim）→ ③事实 BFS（select_facts）→ ④仲裁 → ⑤后处理。本提案把 ②、③ 拆出分别对应 `search`、`associate`，并新增路径搜索（`reason`）。

### 约束

- 不改 MCS 关系模型与查询语义（最小改动）。
- 未实现的能力（向量、热点、随机截断、事件）以空壳占位，诚实标注，不伪造。
- 工具间需传节点 id，支持 LLM 多步导航。

### 利益相关者

- 记忆 agent 用户（导航体验）
- MCS 维护者（核心不动）

---

## Goals / Non-Goals

**Goals:**

1. 5 工具导航体系，LLM 主导导航决策
2. 已实现能力（learn / keyword search / direct search / mcs associate / 路径搜索）扎实可用
3. 未实现能力空壳占位、诚实标注
4. MCS 核心不动（仅加一个公共薄方法）

**Non-Goals:**

- 不实现向量检索 / 热点排序 / 事件节点（各自为独立后续提案，依赖 priority 接入、事件模型落地）
- 不改 MCS 查询语义
- 不引入新外部依赖

---

## Decisions

### Decision 1: 工具是 MCS 能力的薄封装，导航交给 LLM

**选择：** 工具 = MemoryStore 原语 = MCS 能力的封装；系统提示词明确"你负责导航：选工具、选种子、选模式、选两节点"。

**理由：** 记忆 agent 的价值在于让 LLM 根据问题自主决定探索路径（先 keyword 搜入口 → 从种子 mcs 联想 → 找路径），而非一把梭的 query。细粒度工具让导航可控、可解释。

### Decision 2: direct 模式 = 虚拟根高层子图

**选择：** `search(mode=direct)` 返回 `__seed_root__` 的层级子节点（`store.get_out_hierarchy("__seed_root__")`），按 token 预算截断。

**理由：** direct 用于"无明确关键词时从顶层 hub 入手"。根的高层子节点即图的顶层组织中心，是天然入口。按用户定义。

**实现：**
```python
# memory.py（worker 线程内）
def _do_search(self, query, mode):
    if mode == "direct":
        nodes = self._mcs.store.get_out_hierarchy("__seed_root__") or []
        return _render_seeds(nodes)
    if mode == "keyword":
        nodes = self._mcs.query_engine.locate_seeds(query)
        return _render_seeds(nodes)
    if mode == "vector":
        return "[未实现] 向量检索暂不可用，请用 keyword 或 direct"
```

### Decision 3: associate 复用 mcs.query(existing_context=[seed])

**选择：** `associate(seed_id, mode="mcs")` 用 `store.get_node(seed_id)` 取节点，调 `mcs.query("", existing_context=[node])`（跳过种子定位，直接 BFS）。

**理由：** `existing_context` 是 MCS 公共 API，正是"给定种子做 BFS"的语义，零核心改动。hot/random 空壳。

**边界：** seed_id 不存在时 `get_node` 返回 None → 返回错误提示，不抛异常中断 loop。

### Decision 4: 路径搜索在 MemoryStore 层新写

**选择：** `find_path(source_id, target_id)` 用 store 接口做双向 BFS 找最短连通路径，设最大跳数（默认 6），不连通或节点不存在返回文本提示。

**理由：** MCS 无路径搜索。store 接口（property_graph 模式 `get_facts` 双向可达 + `get_out_hierarchy`）足够，不依赖 query_engine。允许失败。

**实现要点：**
```python
def _do_find_path(self, source_id, target_id, max_hops=6):
    store = self._mcs.store
    if store.get_node(source_id) is None or store.get_node(target_id) is None:
        return "[未找到] 节点不存在"
    # 双向 BFS：邻居 = get_facts(n) 端点 ∪ get_out_hierarchy(n)
    # 相遇则回溯路径；max_hops 内不连通 → "[未找到] 两节点不连通"
```

### Decision 5: search 经 QueryEngine.locate_seeds 公共薄方法

**选择：** 给 `QueryEngine` 加公共方法 `locate_seeds(query) -> list[Node]`，薄封装现有 `_locate_seeds`（构造临时 QueryContext），MemoryStore.search(keyword) 调它。

**理由：** `_locate_seeds` 是私有且需 ctx。加一个公共薄方法（不改现有 query 行为）比 MemoryStore 直接调私有更干净，符合"按新逻辑适配基础设施"。属最小核心触碰。

**替代方案：** MemoryStore 直接调 `query_engine._locate_seeds`（碰私有，但不改核心文件）。若评审倾向不动 query_engine，选此。

> 本提案默认选 Decision 5（公共方法）。**待你拍板。**

### Decision 6: 空壳工具诚实

**选择：** 未实现 mode/工具返回 `[未实现] {原因}`，且工具 description 列明"可用模式：..."，引导 LLM 选可用项。

**理由：** 不伪造结果（避免 LLM 误信）、不浪费轮次（description 预告）。

### Decision 7: 多步 id 传递

**选择：** 工具返回文本带节点 id（如 `[id:c1] 名称 — 摘要`），`associate`/`reason` 参数收 id。

**理由：** 导航跨多步，LLM 需在步骤间引用具体节点。

### Decision 8: 旧 query/ingest 原语去留

**选择：** 删除 MemoryStore 旧的 `query`/`ingest` 文本方法，loop 统一走 5 新工具；`learn` 即原 `ingest` 的重命名。

**理由：** mcp-server 不依赖 agent.memory，无外部引用；保留则与 learn/search 冗余。删除更清晰。

### Decision 9: agent 独立成顶层包 mcs_agent

**选择：** `mcs/agent/` → 顶层 `mcs_agent/`；所有 import `mcs.agent.*` → `mcs_agent.*`；`python -m mcs.agent` → `python -m mcs_agent`。单 pyproject 保留，独立 pyproject 留待将来。

**理由：** agent 是应用层，与 MCS 核心解耦；将来分开打包发布需独立包。现在只移目录 + 改 import（最小改动），独立 pyproject 过早复杂化，等真要发布时再加。

**单向依赖：** `mcs_agent` → `mcs`（agent 用 mcs 的 ingest/query/query_engine/store/presets/entities）；`mcs` 核心不反向 import agent。

**实现：**
```bash
git mv mcs/agent mcs_agent
# 内部 import：mcs.agent.* → mcs_agent.*（对 mcs 的 from mcs.* 保留）
# __main__：python -m mcs_agent
# tests/test_agent_*.py：from mcs_agent.* import ...
# pyproject：[agent] deps、包发现
```

**替代方案：**
1. 保留 mcs 子包（不独立）——维持现状，但将来难分开打包，违背用户意图。
2. 现在就拆独立 pyproject（monorepo 两包）——彻底但过早复杂化，本期不做。

---

## 工具 schema（喂 LLM，function calling）

### learn
- **description:** "把一段信息写入记忆图谱（复用 MCS 写管线，自动抽概念入图）。仅当用户明确要求记住时调用。"
- **params:** `text`(string, required)

### search
- **description:** "搜索记忆图谱的种子节点作为导航入口。mode：keyword=按用户输入做关键词/字面匹配（主力，已实现）；direct=返回顶层 hub 节点（无明确关键词时用，已实现）；vector=向量检索（未实现，勿用）。返回节点列表含 id。"
- **params:** `query`(string, required), `mode`(enum[keyword,direct,vector], default keyword)

### associate
- **description:** "从指定种子节点出发做联想扩展（BFS）。seed_id 由 search 返回。mode：mcs=MCS 事实 BFS（已实现，主力）；hot=热点排序（未实现）；random=随机截断（未实现）。返回扩展子图含 id。"
- **params:** `seed_id`(string, required), `mode`(enum[mcs,hot,random], default mcs)

### reason
- **description:** "在两个已知节点间找连通路径（双向最短路径，允许失败）。source_id/target_id 由前序工具返回。找不到则告知无路径。"
- **params:** `source_id`(string, required), `target_id`(string, required)

### recall
- **description:** "回忆近期热点事件。（未实现：依赖事件节点与热点排序，暂不可用。）"
- **params:** `limit`(integer, default 5)

---

## 系统提示词（导航导向）

```
你是一个记忆导航 agent。你不直接背事实，而是通过工具探索记忆图作答：
search 找入口种子 → associate 从种子联想扩展 → reason 找两节点间路径 → recall 看热点 → learn 记新信息。
你决定用哪个工具、哪个种子、哪种模式。先把相关记忆探索充分，再据探索结果回答；记忆不足据实说明。
未实现的模式工具会告知，请改用可用项。
```

---

## Risks / Trade-offs

### Risk 1: 工具数量增加 LLM 选错风险

**缓解：** description 明确"何时用/可用模式"；系统提示词给典型导航流。

### Risk 2: direct 根扁平化返回过多

**缓解：** direct 按 token 预算截断（复用 Trim 思路或简单 top-N）。

### Risk 3: 路径搜索大图慢

**缓解：** max_hops 上限（默认 6），超限视为不连通。

---

## Migration Plan

0. 包独立化：`git mv mcs/agent mcs_agent` + 改内部 import + `__main__` + tests + pyproject + 全量回归。
1. MemoryStore 加 5 原语（learn/search/associate/find_path/recall）+ 节点 id 渲染 helper；删除旧 query/ingest 文本方法（decision 8）。
2. loop.py 换工具表（5 工具 + description）+ 导航系统提示词 + _dispatch。
3. QueryEngine 加 `locate_seeds` 公共薄方法（decision 5）。
4. 测试：loop 5 工具 + 多步 id + 空壳；memory 新原语 + 路径搜索边界；全量回归。

---

## Open Questions

1. **find_path 的 max_hops 默认值**：6 还是按 token 预算动态？（提案默认 6 固定值，简单可预测。）
2. **direct 截断**：按 token 预算（复用 TrimPlugin）还是固定 top-N？（提案默认简单 top-N，如 ≤ 20。）
3. **decision 5 vs 替代**：locate_seeds 加公共方法，还是 MemoryStore 调私有 `_locate_seeds`？（待拍板，默认公共方法。）
