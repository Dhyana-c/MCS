## Why

MCS 当前有一条**隐含假设：所有来源讲的是同一个世界**。于是写入期对齐（同名复用 / 同义合并 / 互斥判定）对所有来源一视同仁。这在"日记 + wiki + 正史"等真实语料上成立，但在**虚构作品**（小说 / 影视 / 游戏设定）上产生核心问题：

**虚构污染真值**：三国演义的"曹操借头安众"（虚构）与三国志的正史记录被 LLM 抽取后挂到**同一个"曹操"节点**；更严重时两者被判【互斥】——但它们不是矛盾，是两个世界的不同叙述。系统把"虚构 vs 真实"误当成"同一世界的事实冲突"。互斥判定缺少"是否同世界"的前置条件。

用户的初始直觉是"做一个子图节点（小说），可内部展开"。分析后收敛为：**不需要硬子图**（封闭子图 + 跨子图边自相矛盾）。正确形式是给节点加**世界归属（universe）维度**，把"封闭"落实为写入期对齐开关、"关联"保持普通关联边（载重过滤的弱桥）。

> **范围说明**：本 change 做 **universe 隔离 + universe 身份（元节点）+ 标识归一**。隔离与归一强耦合（universe 标识不稳则隔离不稳、同世界不同写法会误裂、碎片从第一天积累且越晚修迁移越贵），故一并落地——代价是本 change 从"最薄"变"中厚"，不再是纯隔离的最小增量。作品的**内部时序性发生（带纪年的叙述事件）与叙事时间线**是更深的建模问题——涉及事件层分流与作品事件 LLM 抽取，由后续 `work-narrative-events` change 解决（依赖本 change 的 universe 维度）。本 change 落地后：ingest 一部作品 → 经注册表规范化定 canonical universe、自动建 universe 元节点（身份锚点，不持成员）→ 其概念 / 事实进作品 universe（隔离达成、虚构互斥修复、同世界不同写法可经别名归一）；作品叙述发生暂不抽取，元节点暂不抽作品描述（向后兼容的中间态）。

**契机**：multihop 评测证明 agent 版查询驱动优于框架版 BFS，框架版查询驱动（BFS / 管线）将让位 agent + 工具（底层图模型 Node / Store / 守门 / 聚类仍共用）。"BFS 跨不跨 universe"变成 agent 工具的参数，实现复杂度显著降低。

## What Changes

- **节点加 `universe` 维度**：每个节点（含事件）归属一个 universe。`"__reality__"` 为默认现实世界（无明确作品归属的真实来源共享）；明确来源于某作品（`IngestInput.work_id`）的，该次 ingest 产出的**概念 / 事实 / source**归该作品 universe。**判定靠 `work_id` 元信息、规则入库、MUST NOT 经 LLM**。
- **`work_id` 在本 change 仅判定 universe 归属**：`IngestInput.work_id` 非空 → 本次产出的概念 / 事实 / source `universe = work_id`；为空 → `"__reality__"`。**摄入行为事件**（"读了某作品"这个行为本身）`universe` 固定 `"__reality__"`——它是用户的现实行为、进用户现实时间轴，与被读作品属哪个 universe 无关。本 change **不**因 `work_id` 触发作品事件抽取（那是 `work-narrative-events`）。
- **封闭 = 写入期对齐开关**：同名复用、同义合并、互斥判定、read-repair、后台 dedup MUST 加"同 universe"前置判——跨 universe 不合并、不判互斥。**修复"虚构 vs 真实误判互斥"bug**。
- **跨 universe 桥 = 普通关联边，载重规则过滤**：`演义曹操 —关联— 正史曹操` 是普通关联边（无新边类型）。`get_relations` 载重过滤扩展为双类：**事件边**（同 universe，核心单向不反查——既有）+ **跨 universe 边**（两端 universe 不同，**双向**不反查——新增，含跨 universe 的事件背书边）。**概念桥两类来源**：ingest ⑤ 背书边（事件 `"__reality__"` → 作品 fact，**自动产生**）+ agent 显式 `link_cross_universe` 工具建的概念桥（**摄入不自动建**——② 关联定位维持 universe 限域，避免 LLM 跨 world 乱连）。跨 universe 桥经 agent `get_cross_universe_edges`（只读，带 filter / pagination / limit）可达。
- **不变量精确化为单 universe 内**：核心不变量"任意节点活跃视图 ≤ T"精确为"**单 universe 内**"。每 universe 更小，有界更易成立。
- **单根 + universe 参数**：`__seed_root__` 保持单一固定 id（不破约定），`get_out_hierarchy(root, universe=...)` 按 universe 过滤同 universe 孤儿；**查询 / 守门对 root 调用 MUST 传当前 universe**（否则多 universe 库的 root 视图会混入所有 universe 孤儿、破坏单 universe 不变量；默认参数仅服务旧库兼容）。
- **agent universe 上下文 + 跨 universe 工具**：agent 工具（search / associate）做单 universe 查询时，universe 上下文经工具参数显式传入或从种子节点继承（默认 `"__reality__"`）；跨 universe 能力经两个独立显式工具——只读 `get_cross_universe_edges`（带 filter / pagination / limit）取桥、非 readonly `link_cross_universe` 建概念桥（护栏：两端 universe 相异 / 同对去重 / 不合并 / 不加新边类型）。
- **universe 元节点（身份锚点 + foothold，不持成员）**：每个 canonical universe 对应一个元节点（`node_class=概念`、`universe="__reality__"`——"作品作为现实造物" ≠ "作品所述世界"）。ingest 遇新 universe **自动建**；元节点 **MUST NOT 通过边持有成员**（成员靠 `Node.universe` 标量归属，避免超级 hub），但框架不限制上层因语义挂普通关联边。本 change 不抽作品描述（留 `work-narrative-events`）。
- **universe 标识归一（注册表 + 别名，宁裂不并）**：`work_id` 是原始标注，经 **universe 注册表**（= 元节点别名字面匹配）规范化为稳定 canonical id——命中复用、未命中新建。**两层切开**：归属判定 / 注册表规范化不经 LLM（守铁律）；身份治理（别名登记、universe 合并）人 / agent 显式、保守。**默认宁裂不并**（误裂安全可跨查弥合、误并灾难污染真值）；合并两个已存在 universe 默认不自动、高门槛。
- **修 review 3 处正确性缺口**：① `get_out_hierarchy` 过滤语义自相矛盾（root→作品孤儿边本身跨 universe，"边两端"措辞误滤全部作品孤儿）→ 改为**按 target 成员 universe 单侧过滤**（**阻塞级**，不修 P8 无法落地）；② `get_subgraph` 有界 BFS 直接沿 `_assoc_out` 扩展，是第三个跨 universe 泄漏点 → BFS 按 universe 过滤；③ `get_related_events` 定向查在跨 universe 背书边引入后行为未界定 → 显式声明"跨 universe 背书亦返"（绕载重取出处）。

## Capabilities

### New Capabilities

（无）—— universe 是图模型核心契约的一部分，归 `unified-graph-schema`，不新增 capability。

### Modified Capabilities

- **`unified-graph-schema`**：
  - **新增** `世界归属（universe）维度` requirement：节点（含事件）带 `universe`；`"__reality__"` 默认 + 作品 universe 靠 `IngestInput.work_id` 判定（经注册表规范化）；判定不经 LLM。
  - **新增** `universe 元节点与归一` requirement：每 canonical universe 一个元节点（`概念`、`universe="__reality__"`、不持成员、自动建）；work_id 经注册表别名匹配归一为 canonical id；归属 / 归一不经 LLM；默认宁裂不并、universe 合并高门槛不自动。
  - **修改** `节点分 4 类，不引入领域 type` → 增 `universe` 为与 `node_class` 并列的归属轴。
  - **修改** `核心 / 事件双层，核心不反查事件` → 载重过滤双类（同 universe 事件边单向、跨 universe 边双向）；本 change 阶段事件仍为摄入行为事件（规则、`"__reality__"`），per-universe 事件层由 `work-narrative-events`。
  - **修改** `图质量最终收敛（去重 / 合并）` → 同名 / 同义 / 互斥 / read-repair / dedup 均增"同 universe"前置判。
- **`entities-package`**：**修改** `实体模块内容` → `Node` 增 `universe`（默认 `"__reality__"`），对全部 `node_class`（含事件）生效。
- **`store-interface`**：**修改** `StoreInterface 定义统一存储抽象基类` → `get_relations` 载重过滤增"跨 universe 边双向过滤"；`get_out_hierarchy` 增 `universe` 参数、过滤语义定为**按 target 成员 universe 单侧**（修 review 阻塞级矛盾）；`get_subgraph` 有界 BFS 增 universe 过滤（第三泄漏点）；`get_related_events` 显式界定"跨 universe 背书亦返"；新增 `get_cross_universe_edges` 定向查原语；节点表 schema 增 `universe` 列 + 旧库补默认。（注册表规范化复用现有节点别名查询，store 层无新原语。）

## Impact

- **代码**：
  - `mcs/entities/graph.py`：`Node` 增 `universe: str = "__reality__"`（全 `node_class` 生效，含事件）。
  - `mcs/entities/decisions.py`：`IngestInput` 增 `work_id: str | None = None`（仅用于 universe 判定）。
  - `mcs/stores/{in_memory,sqlite_store}.py`：节点建 / 存带 universe；`get_relations` 增跨 universe 边双向过滤（与既有事件单向过滤并列）；`get_out_hierarchy` 增 `universe` 参数（按 target 成员 universe 单侧过滤）；`get_subgraph` 有界 BFS 邻居扩展增 universe 过滤（第三泄漏点）；`get_related_events` 界定跨 universe 背书亦返；新增 `get_cross_universe_edges`；`SQLiteStore` 节点表增 `universe` 列 + 旧库补列默认 + round-trip 保真。
  - `mcs/core/write_pipeline.py`：ingest 规则入库**经注册表把 `work_id` 规范化为 canonical universe id**（元节点别名字面匹配，未命中**自动建 universe 元节点** `概念`/`universe="__reality__"`）、定 `target_universe`、注入本次产出的概念 / 事实 / source；**摄入行为 event `universe` 固定 `"__reality__"`**；对齐 / 合并 / 互斥（`judge_relations`）+ read-repair 增"同 universe"前置判。
  - `mcs/core/query_engine.py` / `mcs_agent` 工具：查询带 universe 上下文；新增两个跨 universe 工具——只读 `get_cross_universe_edges`（filter / pagination / limit）+ 非 readonly `link_cross_universe` 建概念桥；root 的 `get_out_hierarchy` 调用必传 universe（P8 全量调用点含 query / 守门 / hub_fallback / graph_summary / graph_quality / `mcs_agent`）。
  - 守门 / 聚类 `decide_hub`：fanout 限同 universe；hub 复用限同 universe。
- **测试**（含边界）：universe 判定（有 / 无 `work_id`，不调 LLM）；跨 universe 同名不合并、不互斥（虚构 vs 真实修复——核心收益验证）；同 universe 内仍正常合并 / 互斥；同 universe 事件单向载重 + 跨 universe 边双向过滤；event 跨 universe 背书方向；聚类 fanout 限同 universe；root 单根 + universe 参数过滤（P8）；旧库补默认；摄入行为 event 即使 ingest 作品仍 `"__reality__"`；`link_cross_universe` 建概念桥（建后仅 `get_cross_universe_edges` 可取回 / `get_relations` 仍过滤、同对去重、拒同 universe、不合并）；P8 `get_out_hierarchy` 全量调用点传 universe（query / 守门 / summary / agent 等）；**universe 元节点**自动建（新 work_id）+ 归 `__reality__` + 不持成员（框架不建归属边）；**归一**：work_id 别名命中复用（不误裂）/ 未命中新建（宁裂）/ 注册表规范化不经 LLM / universe 合并默认不自动；**review 3 点**：`get_out_hierarchy` 单侧过滤（root→作品孤儿经 `universe=<work_id>` 单侧取回、验"边两端"误滤已修）、`get_subgraph` BFS 不经概念桥跨 universe 扩展、`get_related_events` 跨 universe 背书亦返而同边 `get_relations` 双向过滤。
- **文档**：`docs/graph-model-design.md` §3.1 增 universe + **universe 元节点（现实造物 vs 所述世界）** + §3.3 载重双类（+ get_subgraph/get_related_events 界定）+ §5.1 ingest universe 判定（经注册表规范化、自动建元节点）+ §7 归一治理（宁裂不并、别名登记、合并高门槛）；`CLAUDE.md` 宪法「节点 4 类」补 universe + 元节点、铁律一不变量精确为单 universe 内、边方向载重补跨 universe 双向；`docs/memory-agent.md` 补跨 universe 工具 + 单 universe 工具 universe 参数。
- **API / 依赖**：无新依赖；`Node` / `IngestInput` 加字段带默认（向后兼容）；旧库自动补 `"__reality__"`（向前兼容）。
- **不变量**：核心不变量精确为"**单 universe 内**活跃视图 ≤ T"（强度不降反升）；铁律一（估算 == 渲染）不变。
- **实现风险**（详见 design）：① event 跨 universe 背书的载重分流；② root 多 universe 孤儿混挂 + `get_out_hierarchy` 单侧过滤语义（P8 / 修 review 阻塞级）；③ agent universe 上下文来源（P7）；④ 旧库迁移补默认；⑤ 框架版与 agent 版过渡期共存；⑥ `get_subgraph` BFS / `get_related_events` 两个隐性跨 universe 点（review）；⑦ 归一误并真值（宁裂不并、universe 合并高门槛不自动兜底）。
- **后续**：`work-narrative-events` change 在本 change 之上做 per-universe 事件层 + 作品叙事事件 LLM 抽取 + 叙事时间线。
