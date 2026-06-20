# 实现任务 — unified-graph-schema

> **状态**：本 change 当前**只固定设计与契约**（`docs/graph-model-design.md` 为权威 + proposal / design / spec），**不含代码实现**。下列 ① 为已交付设计产物；② 为归档前须补的 spec deltas（彻底重构的爆炸半径，**显式认领**）；③ 为实现阶段任务骨架。

---

## ① 设计交付（已固定）

- [x] `docs/graph-model-design.md` —— 权威目标设计（4 类节点 / 谓词落点 / 双层 / 守门=mutation+边吸收 / 收敛 / 预算 / 流程）
- [x] `proposal.md` —— Why / What Changes / 影响（重构性质）
- [x] `design.md` —— 关键决策记录 / deltas / 盲区
- [x] `specs/unified-graph-schema/spec.md` —— 机制契约（SHALL / MUST）

## ② spec deltas（全爆炸半径，显式认领）—— **16 个 capability delta 已建，`openspec validate --strict` 通过**

核心模型：
- [x] `dual-edge-model` —— **REMOVED**（4 条全，label 事实边模型）
- [x] `attribute-node-model` —— **REMOVED**（6 条全，relation_model 开关 + 双模式）
- [x] `entities-package` —— **MODIFIED**（Edge: kind/label→type；Node: 加 node_class、hub 降标记）
- [x] `subgraph-bounding` —— **MODIFIED**（单模型活跃视图 + 守门挂 mutation；一进多出走关联边；中间概念归纳 role→hub 标记；边吸收=既有 hub 复用 requirement）

存储 / 边：
- [x] `store-interface` —— **MODIFIED**（add_edge 用 type；get_facts/get_assoc→get_relations；持久化列 type）
- [x] `seed-graph-hierarchy` —— **MODIFIED**（边仅关联/互斥；邻接 get_relations；核心 BFS；hub 由标记非 role）
- [x] `store-provenance` —— **MODIFIED/REMOVED**（出处去 relation_model；删 relation_model 硬拒）
- [x] `edge-extension-model` —— **MODIFIED**（get_relations；示例去 label）

渲染 / 配置 / LLM：
- [x] `llm-interaction` —— **MODIFIED/REMOVED**（render_facts/judge 去 label；删两条 attribute_node 模式）
- [x] `result-rendering` —— **MODIFIED**（render_query_result 去 relation_model）
- [x] `mcp-server` —— **MODIFIED**（query 渲染去 relation_model）
- [x] `config-file-loading` —— **MODIFIED**（preset 去 relation_model 参数）
- [x] `graph-summary` —— **MODIFIED**（should_run 触发 role→node_class=概念）
- [x] `graph-visualization` —— **MODIFIED**（graph_view get_relations、序列化去 relation_model/role/kind/label→node_class/type、前端按 type/node_class）

> 已确认**非引用**（误报）：`claude-llm-adapter` / `ollama-llm-adapter` 的 `role="user/system"` 是 LLM API 消息角色，与节点 role 无关。
> 待确认：`openspec/specs/INDEX.md`（spec 索引，含 relation_model/label 字样）——归档时随索引刷新，非 capability delta。

## ②′ 宪法（已改）

- [x] **宪法 `CLAUDE.md`** —— 已重写为统一图模型（4 类节点 / 谓词落点 / 边仅 关联·互斥 / 双层 / 守门=改图即把关 / W=S+T+R），删 `relation_model`，铁律一去模式分支；加过渡说明（宪法领先代码，迁移由本 change 跟踪）。

## ③ 实现阶段任务骨架

### 数据结构（entities）
- [x] `Node` 加 `node_class ∈ {概念,事实,事件,source}`；`hub` 降为标记字段
- [x] `Edge`：`kind`/`label` → `type`（仅 `关联`/`互斥`）；登记制校验
- [x] 序列化 / store 层适配（`extensions_json` 等）

### 核心算法
- [x] 守门：挂在写 / 连边 / 合并 / 读修复后；活跃视图估算（口径 == 渲染、`type` 不计）
- [x] 聚类裂变 `decide_hub`：语义归纳、事实只重组不合并、允许重叠、滤幻觉 id
- [x] 边吸收：新中心 H 生成后，子节点 ⊇ H 成员的 X 改连 H
- [x] 双层：事件层单向绑入、核心不反查（尤其"用户"）、时间倒排截断、帧相对
- [x] 上下文预算 `W = S + T + R`（`R=T` 默认）

### 写入（write-pipeline）
- [x] 规则入库：事件按结构直存、source 按类型切分（不经 LLM）
- [x] 关联节点提取：复用 read 检索已有节点
- [x] LLM 抽取 + 对齐：概念 / 事实，合并同义 / 判互斥 / 连背书

### 查询（query-pipeline）
- [x] 核心 BFS（沿关联）+ 四工作区（积累 / 活跃 / visited / frontier）
- [x] read-repair：读时合并同名 / 同义（过守门、超 T 或需消歧则挂起）
- [x] 按需 `事实 → 事件` 定向查；`purpose` 字段可见性

### 质量收敛
- [x] 去重 / 合并的读写触发路径；后台维护扫描（可选）

### 验证（唯一脆性 = 抽取质量）
- [ ] 记忆样本量化"概念 vs 事实"抽取准确率、转述嵌套（读到的 / 听说的 / 书里的）不污染时间轴
- [ ] multihop-rag：谓词落点模型回归基线
- [ ] 现有 db 迁移：新库重建（评测库）

---

## 待定决策（实现前拍板）

- [ ] 语义边类型起步集（除 `互斥` 外，因果 / 背书是否引入、何时）
- [x] 登记制实现形态
- [ ] 事件 / source 的 `extensions` 字段约定（timestamp / 帧 / 参与者 / source_type）
- [ ] 后台维护扫描的触发与算力预算
