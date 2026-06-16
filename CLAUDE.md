# MCS — 最大上下文子图（Maximum Context Subgraph）

> 项目宪法。下列不变量与铁律**不得违背**；变更若冲突，先改本宪法（经评审）再改代码。
> 规范细节见 `openspec/specs/`（`subgraph-bounding`、`architecture`）。

MCS 把知识组织成概念图，并维持一条硬不变量，使任意节点的**活跃双向视图**（关系边 + 层级邻居）永远放得进一个 LLM 上下文窗口。导航、归纳、查询都建立在此之上。

## 核心不变量（不得违背）

**任意节点的活跃双向视图（top-priority 的 {关系边 + 层级邻居}，截断后）渲染 token ≤ T。** 关系边组成随 `relation_model`：`property_graph`（默认）= 出事实 + 入事实；`attribute_node` = 无类型关联边 + 关联端点（含属性节点）。

**关系表示可插拔**（`relation_model`，默认 `property_graph`，**建图时选定、写入与查询须同模式；混库为未定义行为**）：
- `property_graph`（默认，基线）：关系为带 label 事实边（`主 —谓→ 宾`）。本宪法对 label 事实边的全部硬约束**仅适用此模式**；默认行为逐字不变。
- `attribute_node`：关系具体化为**属性节点**（`role="attribute"`，content 持单一简短说法）+ **无类型关联边**（`kind="assoc"`，无 label）。详见 `attribute-node-model`。

下列铁律在**每种模式内**逐字成立，仅"关系边是什么 / 怎么算 token"随模式切换。

**"有界"指活跃 / 渲染视图，不指存储**——存储可保留低 priority 长尾，靠优先级沉底 / 遗忘降权。溢出靠归纳（出边侧 fanout） / 优先级截断（入边侧） / 遗忘降权（Phase 2）。含虚拟根 `__seed_root__`。出边侧超 T 时必须立即聚类裂变收敛；入边侧仅按 priority 截断（不聚类，会坏归属语义）。
> 反例（曾发生）：`__seed_root__` 扁平直挂 1284 个概念——不变量被破坏，根因见铁律一。

## 两条铁律

1. **估算口径 == 渲染口径（随 `relation_model`）**：判断"活跃视图是否超 T"的估算，必须与 `context_renderer` 实际渲染逐字一致（同字段、同 name==content 去重，**含该模式关系边渲染 token**）。`property_graph` 模式计事实边（`主 —label→ 宾`）token；`attribute_node` 模式计关联边（`主 — 宾`，无 label）+ 属性节点 token。禁止用更少字段（如只算 `content`、漏 `name`、漏关系边 token）低估——低估漏判、直接破坏不变量（1284 即此坑）。
2. **归纳必须 LLM 语义**：中间 hub 由 `decide_hub` 语义归纳，禁止用连通分量 / Louvain 等纯图聚类替代（语义边稀疏时聚不出有意义的类）。图结构仅作辅助信号。

## 算法原理

> **优化判据**：一切重组（裂变 / 重叠 / 复用）以**降低总 token / 节点 / 边数**为准；总量不降的重组无效，不做。

- **渲染**：节点 = `name` + `content`，name==content 只写一份；`property_graph` 模式关系边 = `主 —label→ 宾`（事实边），`attribute_node` 模式关系边 = `主 — 宾`（无类型关联边，属性节点按节点渲染）；估算与渲染共用此函数（铁律一，口径随模式）。
- **守门**：每次写入后检查受影响节点（尤其 root）**出边侧层级视图**（中心 content + 层级子节点，**不含事实 token**——`decide_hub` 只看节点、聚不了事实边）——≤ T 放行；**即将超 T 即主动触发裂变**（不分批，取中心 + 全部层级子节点一次性喂 `decide_hub`），对**任意**超预算节点适用。事实 token 的有界由查询渲染期 Phase 2 按 priority 截断兜；入边侧不聚类，仅查询渲染期按 priority 截断。
- **聚类裂变（一进多出）= 对知识重组**：取中心点 + **出边侧全部成员**（不变量保证 ≤ T，一次装下）→ `decide_hub` 分成**多个语义内聚的社区** → 每个社区按下述方式重组 → 中心点出边侧**一步**收敛。重组后**允许一个节点属于多个父**（重叠），无法归类者留中心点下（不丢）、幻觉 id 过滤。**关系边（`property_graph` 的 fact / `attribute_node` 的 assoc）不被此手术波及**——fanout 只动 hierarchy。
- **重组三方式**（聚类的本质是知识重组，非机械分组）：① **合并同义**——旧的同义概念合并为一；② **找到关键概念（重点）**——识别社区里的**关键概念**，让其余概念关联它、以它为组织中心；③ **概括成新概念**——无现成关键概念时，把这组概念**概括**成一个新概念并与旧概念关联。**禁止空洞聚合标签**（如"信息碎片集合""综合信息枢纽"）。
- **hub 对 LLM 同构**：`role="hub"` 仅供系统识别层级 / 可观测；渲染给 LLM 时与普通概念无异（name+content，无特殊标记）。"hub" 不过是**恰好成为组织中心的普通概念**（关键概念 / 概括概念），不是特殊节点类型。
- **hub 复用（边吸收）**：hub H 生成后，若某节点 X 的一跳子节点 ⊇ H 的全部成员，把 X 改为直连 H（删 X→各成员、加 X→H），减边、减 X 扇出、复用已有 hub。
- **递归**：新 hub 若仍超 T，重复裂变，直到图中**处处**一跳邻域 ≤ T。

## 总体流程

- **写入 `ingest`**：`extract_concepts`（抽概念）→ `judge_relations`（判关系 / 合并，**按 `relation_model` 分支**：`property_graph` 关系落带 label 事实边、`attribute_node` 关系落属性节点 + `kind="assoc"` 边；一条事实/关联只存一份、两端可达）→ `decide_directions`（扩展）→ 挂 `__seed_root__`（**仅孤儿**——零关系关联的概念才挂 root：`get_facts ∪ get_assoc` 皆空；有关联者经关联可达。**`attribute_node` 模式 MUST 用 `get_assoc` 判孤儿**，否则 `get_facts` 恒空 → 全概念挂 root → 根扁平化破坏不变量）→ **主动守门 + 整窗单次裂变**（不分批、全局任意节点）→ `persist`（`save_full`，逐条保真）。
- **查询 `query`**：种子定位（**jieba 切词 + 字面匹配概念名 / 别名**为主力，embedding 兜底，root 仅最后退路；**反查 + 多种子**让入口只需一个 foothold）→ 子图扩展（**事实 BFS**，每节点渲染活跃双向视图，**关系边来源按 `relation_model` 切换**：`property_graph` 取 `get_facts`、`attribute_node` 取 `get_assoc`；LLM 选关系边、端点补入）→ 后处理（重排 / 裁剪）→ `Subgraph`（nodes + 选中关系边：`property_graph` 为 fact、`attribute_node` 为 assoc）。

## 边方向

**关系表示随 `relation_model` 可插拔**；全图边均为单向 `source → target`：

- **层级边** `父→子`：`kind="hierarchy"`，单向、无 label，结构骨架，驱动导航下钻。hub 由 `role="hub"` 识别。（两模式共有。）
- **事实边** `主 —谓→ 宾`：`kind="fact"`，带 `label`（粗粒度谓词）、带 `priority`（为遗忘预留）。**仅 `property_graph` 模式**承载关系语义。**一条事实只存一份**（保留方向语义），但**两端邻接都索引到它**（支持反查）。**禁止自动镜像反向**——反向若是不同语义则为独立事实。
- **无类型关联边** `主 — 宾`：`kind="assoc"`，**无 label**、表"两概念相关 / 共现"，**仅 `attribute_node` 模式**承载关系连接（关系语义由属性节点 content 承载，不在此边）。一条只存一份、两端邻接都索引到它、按 `(source, target)` 去重。
- 层级关系为**纯下行单向边** `父→子`（无成员上行边）。
- `get_out_hierarchy` 返回层级出边目标（驱动下钻）；`get_facts` 返回该节点作**源或宾**的事实边（反查，双向可达）；`get_assoc` 返回该节点作**任一端**的 `kind="assoc"` 关联边（`property_graph` 模式无此边、返回空）。属性节点（`role="attribute"`）经 assoc 连接、**不在层级骨架、不参与 fanout 收敛**，其 token 属关系侧、Phase 2 截断兜。
- **边 / 点扩展对称**：`Edge.extensions` 与 `Node.extensions` 对称——插件经 `EdgeExtensionInterface`（`PluginType.EDGE_EXTENSION`）向边挂字段，逐条随边保真存取 / 反查 / 重组（`edges.extensions_json` 列，与节点同构）；`render(edge, purpose)` 返回 `None` 即该 purpose 下隐藏（字段级可见性，与节点扩展同判定规则）。边渲染函数 `render_fact_edge` / `render_assoc_edge` 带 `purpose` 参以支持按 purpose 切换可见性。
- **`priority` 为派生值**：目标态由 `PriorityScorer` 从边扩展字段算、非写入方权威原语；Phase 1 默认 `0.0`（seam 已引入、未接写路径），`edges.priority` 列作 Phase 2 派生值缓存。**铁律一 / 守门口径不变**——守门只估节点层级视图、不渲染 / 不估算关系边；边渲染 == 估算属**查询侧** token 计数正确性（`estimate_*_edge` 委托 `render_*_edge`），与守门铁律一无关。

## 开关 / 工程

- 分层种子图由 `seed_graph_bounding` 驱动，**默认开**（保证核心不变量）；`token_budget.T ≈ W/2`。
- 关系表示模式 `relation_model`（`property_graph` 默认 | `attribute_node`），建图时选定、写入与查询须同模式；混库为未定义行为。`property_graph` 为基线、行为逐字不变；`attribute_node` 为用户可选项（属性节点 + 无类型关联边）。
- 运行用根目录 `.venv`；测试 `.venv\Scripts\python.exe -m pytest -q`，须保持默认基线行为不变。
- 规范在 `openspec/specs/`，变更走 `openspec/changes/`。
- 插件体系：统一基类 `core/plugin.py`（`Plugin` + `PluginType`），各接口继承它、`PluginManager` 按 `PluginType` 索引（多接口插件经 `get_types()` 登记到每个类型）；详见 `openspec/specs/plugin-protocol`。插件类型包括：`ENTRY`、`TRIM`、`ARBITRATION`、`WRITE_PREPROCESS`（写入管线阶段 ①）、`QUERY_PREPROCESS`（查询管线阶段 ①）、`POSTPROCESS`、`COMPACTION`、`INDEX`、`LLM`、`NODE_EXTENSION`、`EDGE_EXTENSION`、`STORAGE_SCHEMA_EXT`、`MAINTENANCE`、`SEED_SELECTOR`。`PREPROCESS` 已废弃，指向 `WRITE_PREPROCESS`。
- 评测框架：启动脚本和库代码均在顶层 `bench/` 目录（按评测类型分类）。详见 `bench/README.md`。

# 工作规范
- **先理解后动手**：编写 proposal 或代码之前，必须完全了解本系统的设计以及每个类的职责。遇到不清楚的地方，先向用户确认，不得凭猜测推进。
- **禁止跳过理解直接编码**：包括编写 OpenSpec proposal、实现代码、修改代码等所有工作，都必须在充分理解相关模块的设计意图和类职责之后进行。

# 编码规范
- **所有 import 放到文件开头**：Python 文件的所有 import 语句必须集中在文件顶部，禁止在代码中间出现 import。标准库、第三方库、项目内模块按此顺序分组，组间空一行。