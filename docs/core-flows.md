# MCS 核心流程

> 本文档说明 MCS 的两条核心管线（写入、查询）和图演化机制。

## 写入管线（Ingest）— 7 段

写入管线把原始文本组织成由概念节点 + 单向有向边构成的图。

```
input: text
① 前置插件链 (可选)
② 关联节点定位 ◄─ 复用读流程
③ 概念提取 (LLM)
④ 关系判定 (LLM) → DecisionList
⑤ 图更新 (无 LLM)
⑥ 压缩判定插件链 (条件触发)
⑦ 自动落盘 (StorageInterface 增量持久化)
OUTPUT: 图状态更新 + 已持久化
```

### ① 前置插件链（WritePreprocess）

可选的写入前置处理。Phase 1 的 `IdempotencyCheckPlugin` 在此阶段检查 `(doc_id, chunk_id, content_hash)` 是否已摄入，若命中则设 `ctx.skip=True` 短路后续流程。

### ② 关联节点定位

复用读流程定位与输入文本相关的已有节点。这是读写对称性的体现——写入时先"读"图找到锚点，再决定如何并入新知识。

### ③ 概念提取（LLM）

调用 LLM 从输入文本中提取概念。每个概念包含 `name` 和 `content`（描述）。

### ④ 关系判定（LLM）

调用 LLM 判定提取出的概念与已有节点之间的关系。产出 `DecisionList`，包含：
- 存在性判定：该概念是否已以某个节点 X 的形式存在于图中
- 关系判定：概念间的邻接关系
- 合并判定：是否应与已有节点合并

关系以**两条对向单向边**（`a→b` 与 `b→a`）表达。

> **`relation_model` 分支**：`property_graph`（默认）产带 label 事实边决策；`attribute_node`
> 产"建属性节点 + 无类型关联边"决策（`create_attribute`，无 label）。

### ⑤ 图更新（无 LLM）

根据 `DecisionList` 更新图结构：
- 新建节点 + 挂到 `__seed_root__`（单条下行 `root→concept`）
- 建立语义边（双向）
- 合并同义节点

> **按 `relation_model` 分支**：`property_graph` 建事实边；`attribute_node` 建属性节点 +
> `kind="assoc"` 边。孤儿挂根判定为 `get_facts ∪ get_assoc` 皆空（否则 `attribute_node` 模式
> `get_facts` 恒空 → 全概念挂 root → 根扁平化破坏不变量）。

### ⑥ 压缩判定插件链（Compaction）

条件触发。检查受影响节点（尤其 root）的一跳邻域是否逼近 token 预算 T。若即将超 T，主动触发**聚类裂变**。

### ⑦ 自动落盘（StorageInterface）

增量持久化到 SQLite。每次 `ingest()` 完成后，变更的节点和边自动持久化。

## 查询管线（Query）— 5 段

查询管线基于 query 返回与之语义相关的节点集合（`List[Node]`）。

```
input: query, [ctx]
① 前置插件链 (可选)
② 种子定位 (入口插件链+裁剪)
③ 语义理解 Loop (BFS + visited + 上限)
④ 仲裁 (≤1, 单一职责)
⑤ 后置处理链 (0..N, 串联)
OUTPUT: List[Node]
```

### ① 前置插件链（QueryPreprocess）

可选的查询前置处理。

### ② 种子定位

入口插件链 + 裁剪。Phase 1 的种子定位策略：
- **AliasEntry**：通过别名/关键词倒排索引命中种子节点（检索主力）
- **HubFallback**：从持久虚拟根 `__seed_root__` 沿单向出边 `navigate_hub` 下钻（分层种子图导航）

`visited` 集合防止环路。语义边参与导航。

### ③ 语义理解 Loop

BFS 遍历，从种子节点出发，沿出边扩展邻居。受 `visited`、`max_rounds`、`max_picked` 约束。按 token 预算贪婪扩展全邻居。

> **关系边来源按 `relation_model` 切换**：`property_graph` 取 `get_facts`、`attribute_node`
> 取 `get_assoc`（含属性节点端点）；遍历机制（visited / 分层分批 / 回退）两模式一致。

### ④ 仲裁

最多 1 个仲裁插件，单一职责。Phase 1 无仲裁（accumulated 直通）。

### ⑤ 后置处理链

0..N 个后置插件，串联执行。Phase 1 的 `DocRerank` 在此阶段对结果按查询相关性重排。

## 图演化

图不是静态的——随着知识摄入，图通过以下机制自组织生长。

### 聚类裂变（一进多出）

当某节点的一跳邻域逼近 token 预算 T 时，触发聚类裂变：

1. 取中心点 + **全部**一跳子节点（不变量保证 ≤ T，一次装下）
2. 调用 `decide_hub` 分成**多个语义内聚的社区**
3. 每个社区按重组三方式之一处理
4. 中心点一跳邻域**一步**收敛

### 重组三方式

聚类的本质是知识重组，非机械分组：

1. **合并同义**：旧的同义概念合并为一
2. **找到关键概念**：识别社区里的关键概念，让其余概念关联它、以它为组织中心
3. **概括成新概念**：无现成关键概念时，把这组概念概括成一个新概念并与旧概念关联

**禁止空洞聚合标签**（如"信息碎片集合""综合信息枢纽"）。

### Hub 复用（边吸收）

hub H 生成后，若某节点 X 的一跳子节点 ⊇ H 的全部成员，把 X 改为直连 H（删 X→各成员、加 X→H），减边、减 X 扇出、复用已有 hub。

### Hub 对 LLM 同构

`role="hub"` 仅供系统识别层级 / 可观测；渲染给 LLM 时与普通概念无异（name+content，无特殊标记）。"hub" 不过是**恰好成为组织中心的普通概念**，不是特殊节点类型。

### 递归收敛

新 hub 若仍超 T，重复裂变，直到图中**处处**一跳邻域 ≤ T。

## 守门机制

每次写入后检查受影响节点（尤其 root）一跳邻域——≤ T 放行；**即将超 T 即主动触发裂变**（不分批，取中心 + 全部一跳子节点一次性喂 `decide_hub`），对**任意**超预算节点适用。

## 进一步阅读

- [架构总览](architecture.md) — 系统定位、双层结构、插件体系
- [技术方案](technical-design.md) — 完整的机制设计文档
- [Write Pipeline Spec](../openspec/specs/write-pipeline/spec.md) — 写入管线契约
- [Query Pipeline Spec](../openspec/specs/query-pipeline/spec.md) — 查询管线契约
- [Subgraph Bounding Spec](../openspec/specs/subgraph-bounding/spec.md) — 最大上下文子图不变量契约
