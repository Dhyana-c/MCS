# MCS — 最大上下文子图（Maximum Context Subgraph）

> 项目宪法。下列不变量与铁律**不得违背**；变更若冲突，先改本宪法（经评审）再改代码。
> 规范细节见 `openspec/specs/`（`subgraph-bounding`、`architecture`）。

MCS 把知识组织成概念图，并维持一条硬不变量，使任意节点的"局部视野"（它 + 一跳子节点）永远放得进一个 LLM 上下文窗口。导航、归纳、查询都建立在此之上。

## 核心不变量（不得违背）

**任意节点 + 它的全部一跳子节点，渲染成 LLM 输入的 token 数 ≤ 一个上下文窗口 T。**

含虚拟根 `__seed_root__`。一旦某节点一跳邻域逼近 T，必须立即聚类裂变收敛回 ≤ T。
> 反例（曾发生）：`__seed_root__` 扁平直挂 1284 个概念——不变量被破坏，根因见铁律一。

## 两条铁律

1. **估算口径 == 渲染口径**：判断"邻域是否超 T"的估算，必须与 `context_renderer` 实际渲染逐字一致（同字段、同 name==content 去重）。禁止用更少字段（如只算 `content`、漏 `name`）低估——低估漏判、直接破坏不变量（1284 即此坑）。
2. **归纳必须 LLM 语义**：中间 hub 由 `decide_hub` 语义归纳，禁止用连通分量 / Louvain 等纯图聚类替代（语义边稀疏时聚不出有意义的类）。图结构仅作辅助信号。

## 算法原理

> **优化判据**：一切重组（裂变 / 重叠 / 复用）以**降低总 token / 节点 / 边数**为准；总量不降的重组无效，不做。

- **渲染**：节点 = `name` + `content`，name==content 只写一份；估算与渲染共用此函数（铁律一）。
- **守门**：每次写入后检查受影响节点（尤其 root）一跳邻域——≤ T 放行；逼近 / 超 T 触发裂变。
- **聚类裂变（一进多出）= 对知识重组**：取中心点 + **全部**一跳子节点（不变量保证 ≤ T，一次装下）→ `decide_hub` 分成**多个语义内聚的社区** → 每个社区按下述方式重组 → 中心点一跳邻域**一步**收敛。重组后**允许一个节点属于多个父**（重叠），无法归类者留中心点下（不丢）、幻觉 id 过滤。
- **重组三方式**（聚类的本质是知识重组，非机械分组）：① **合并同义**——旧的同义概念合并为一；② **找到关键概念（重点）**——识别社区里的**关键概念**，让其余概念关联它、以它为组织中心；③ **概括成新概念**——无现成关键概念时，把这组概念**概括**成一个新概念并与旧概念关联。**禁止空洞聚合标签**（如"信息碎片集合""综合信息枢纽"）。
- **hub 对 LLM 同构**：`role="hub"` 仅供系统识别层级 / 可观测；渲染给 LLM 时与普通概念无异（name+content，无特殊标记）。"hub" 不过是**恰好成为组织中心的普通概念**（关键概念 / 概括概念），不是特殊节点类型。
- **hub 复用（边吸收）**：hub H 生成后，若某节点 X 的一跳子节点 ⊇ H 的全部成员，把 X 改为直连 H（删 X→各成员、加 X→H），减边、减 X 扇出、复用已有 hub。
- **递归**：新 hub 若仍超 T，重复裂变，直到图中**处处**一跳邻域 ≤ T。

## 总体流程

- **写入 `ingest`**：`extract_concepts`（抽概念）→ `judge_relations`（判关系 / 合并，连双向语义边）→ `decide_directions`（扩展）→ 挂 `__seed_root__`（有向下行 `out`）→ **守门 + 聚类裂变** → `persist`（`save_full`，方向保真）。
- **查询 `query`**：种子定位（alias / 从 root 沿 `out` 边 `navigate_hub` 下钻，`visited` 防环）→ 子图扩展（按 token 预算贪婪扩展全邻居）→ 后处理（重排 / 裁剪）→ `List[Node]`。

## 边方向

层级边**有向**（父→子、成员→原父，均 `out`），导航只沿 out 下钻防成环；语义边**双向**（`bidirectional`）保召回。方向落库 round-trip 保真（边键含 direction，同对 out/bidi 可共存）。

## 开关 / 工程

- 分层种子图由 `seed_graph_bounding` 驱动，**默认开**（保证核心不变量）；`token_budget.T ≈ W/2`。
- 运行用根目录 `.venv`；测试 `.venv\Scripts\python.exe -m pytest -q`，须保持默认基线行为不变。
- 规范在 `openspec/specs/`，变更走 `openspec/changes/`。
- 插件体系：统一基类 `core/plugin.py`（`Plugin` + `PluginType`），各接口继承它、`PluginManager` 按 `PluginType` 索引（多接口插件经 `get_types()` 登记到每个类型）；详见 `openspec/specs/plugin-protocol`。插件类型包括：`ENTRY`、`TRIM`、`ARBITRATION`、`WRITE_PREPROCESS`（写入管线阶段 ①）、`QUERY_PREPROCESS`（查询管线阶段 ①）、`POSTPROCESS`、`COMPACTION`、`INDEX`、`LLM`、`NODE_EXTENSION`、`STORAGE_SCHEMA_EXT`、`MAINTENANCE`、`SEED_SELECTOR`。`PREPROCESS` 已废弃，指向 `WRITE_PREPROCESS`。
- 评测框架：启动脚本在顶层 `bench/` 目录（按评测类型分类），库代码在 `mcs/bench/` 包内。详见 `bench/README.md`。

# 工作规范
- **先理解后动手**：编写 proposal 或代码之前，必须完全了解本系统的设计以及每个类的职责。遇到不清楚的地方，先向用户确认，不得凭猜测推进。
- **禁止跳过理解直接编码**：包括编写 OpenSpec proposal、实现代码、修改代码等所有工作，都必须在充分理解相关模块的设计意图和类职责之后进行。

# 编码规范
- **所有 import 放到文件开头**：Python 文件的所有 import 语句必须集中在文件顶部，禁止在代码中间出现 import。标准库、第三方库、项目内模块按此顺序分组，组间空一行。