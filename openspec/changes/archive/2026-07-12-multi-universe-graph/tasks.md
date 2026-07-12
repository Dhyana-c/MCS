# Implementation Tasks

## 0. Schema 与默认值（前置，向后 / 向前兼容）

- [x] 0.1 `mcs/entities/graph.py`：模块顶部定义常量 `REALITY_UNIVERSE = "__reality__"`；`Node` dataclass 增 `universe: str = REALITY_UNIVERSE`（默认**引用常量、非字面量**，避免双处魔法字符串漂移；位置在 `node_class` 之后、`extensions` 之前）。对**全部 `node_class`**（含事件）生效。
- [x] 0.2 旧 `Node(...)` 调用点全量扫描：不传 `universe` 的构造 MUST 仍可用（默认 `__reality__`，向后兼容）；`Node` 重建 / 反序列化路径（store `load` / `save_full` / snapshot）MUST 透传 `universe`。
- [x] 0.3 `mcs/stores/sqlite_store.py`：节点表建表 SQL 增 `universe TEXT NOT NULL DEFAULT '__reality__'` + `CREATE INDEX ... ON nodes(universe)`；既有"打开时补列"机制补 `universe` 列、旧库全部填默认 `"__reality__"`（含事件节点——旧事件均现实，行为等价）。
- [x] 0.4 `mcs/stores/sqlite_store.py`：`save_full` / `load` round-trip 逐条保真 `universe`（含多 universe 节点）。

## 1. Store 载重双类过滤 + universe 参数 + 跨查原语

- [x] 1.1 `mcs/stores/in_memory.py` `get_relations`：**既有事件单向过滤扩展为带 universe**（核心节点过滤对端=事件、且两端**同 universe** 才走既有单向过滤逻辑——当前代码无 universe 概念，"同 universe"是本 change 新增）；**新增**跨 universe 边**双向**过滤——两端 `universe` 不同时，两端 `get_relations` 都 MUST NOT 返回该边（含跨 universe 事件背书边）。
- [x] 1.2 `mcs/stores/sqlite_store.py` `get_relations`：与 1.1 对齐（双实现一致）。
- [x] 1.3 `get_out_hierarchy(node_id, universe=None)`：增可选 `universe` 参数，过滤语义 = **按 target 成员 `universe` 单侧判定**（`universe=U` → 只返 `target.universe==U`；`universe=None` → 全返，仅旧库兼容）。**MUST NOT 用"边两端同 universe"语义**——root→作品孤儿边本身跨 universe，边两端措辞会误滤全部作品孤儿（D4 修 review 阻塞级矛盾）；`__seed_root__` 调用时 `universe=U` 取 `target.universe==U` 孤儿（无视 root 自身 `__reality__`）。
- [x] 1.4 新增定向查原语 `get_cross_universe_edges(node_id, limit=None) -> list[Edge]`（绕载重、取该节点跨 universe 桥，供显式跨查工具用）；双实现一致。
- [x] 1.5 `get_subgraph`（in_memory / sqlite 有界 BFS，直接沿 `_assoc_out` 扩展）：BFS 邻居扩展 MUST 按 universe 过滤——概念桥 / 跨 universe 边 MUST NOT 被 BFS 展开（第三泄漏点，漏则 `link_cross_universe` 桥使活跃视图跨 universe 爆 T）；双实现一致。
- [x] 1.6 `get_related_events`（定向查、绕载重）：显式界定跨 universe 背书亦返——对作品 fact 定向查 SHALL 返回其现实摄入背书事件（要出处），而同边 `get_relations` 仍双向过滤（不进活跃视图）。补测试锁定此语义（不留白）。

## 2. ingest universe 判定（work_id 仅判 universe，不触发抽取）

- [x] 2.1 `mcs/entities/decisions.py`：`IngestInput` 增 `work_id: str | None = None`（仅用于 universe 判定）。`ingest(str)` 归一化路径零改动（无 `work_id` → 现实）。
- [x] 2.2 `mcs/core/write_pipeline.py` 规则入库（`_build_event_node` / `_build_source_nodes`）：按 `work_id` 定 `target_universe`（无 → `__reality__`；有 → **经注册表规范化的 canonical id**，见 2.8）；**摄入行为 event `universe` 固定 `__reality__`**（行为归属现实，不随被读作品变）；source 节点 `universe` = `target_universe`。
- [x] 2.3 抽取 / 连边（③④）：本次新建 / 命中的概念 / 事实 `universe` 注入 = `target_universe`。
- [x] 2.4 对齐 / 合并（`_dispatch_merge` / `_merge_concept_into`）：增"同 `universe`"前置判——候选集先按 universe 过滤，跨 universe MUST NOT 合并。
- [x] 2.5 互斥判定（`judge_relations` 产 `Decision.mutex_with` + 第二遍建 `互斥` 边）：增"同 `universe`"前置判——跨 universe MUST NOT 产 `mutex_with`（修虚构 vs 真实误判互斥 bug）。
- [x] 2.6 read-repair 合并（`query_engine._try_read_repair`）：增"同 `universe`"前置判。
- [x] 2.7 后台 dedup（`dedup_maintenance.py`）：增"同 `universe`"前置判。

## 2A. universe 注册表 + 元节点归一（D6 / D7，两层切开、宁裂不并）

- [x] 2.8 注册表规范化 `work_id → canonical universe id`（`write_pipeline`，**不经 LLM**）：复用现有节点别名字面查询，按元节点 `name` + 别名匹配已有 universe 元节点——命中复用其 canonical id；未命中触发 2.9 新建。**store 层无新原语**（复用 `query_nodes` / 节点别名索引）。`metadata` 内同名键 MUST NOT 参与。
- [x] 2.9 元节点自动建（新 canonical universe）：`write_pipeline` 遇未命中的 `work_id` 建 universe 元节点——`node_class=概念`、**`universe="__reality__"`**（作品作为现实造物）、`name=作品标注`、`content` 可空 / 简述（**不抽作品描述**）；元节点作 canonical id 载体（canonical id = 元节点 id 或稳定 slug，实现时定并记 design）。**MUST NOT 自动建"成员 → 元节点"归属边**（不持成员，防超级 hub）。
- [x] 2.10 归一治理入口（保守、显式）：① **别名登记**——把同世界不同写法登记为元节点别名（agent 工具 / 配置；复用节点别名设施）；② **universe 合并**——两个已存在 canonical universe 合并为人 / agent 显式高门槛动作，框架**默认不自动**（最危险、误并污染真值）。本 change 提供入口 + 默认关闭自动合并；宁裂不并。

## 3. 守门 / 聚类 per-universe + 虚拟根（P8）

- [x] 3.1 聚类裂变 fanout（`mcs/plugins/maintenance/fanout_reducer.py` 的 `_decide_hub` 及其调用点）：邻域成员 MUST 限定同 universe（跨 universe 节点不参与聚类）。
- [x] 3.2 边吸收 / hub 复用（`fanout_reducer.py`）：只吸收同 universe 成员。
- [x] 3.3 虚拟根 `__seed_root__`：保持单一固定 id（D4）；`get_out_hierarchy(root, universe=...)` 按 universe 过滤同 universe 孤儿。**P8 全量调用点**（grep `get_out_hierarchy`，漏一处即破坏单 universe 不变量 + 铁律一）MUST 传当前 universe——已知含：`core/query_engine.py`、`core/write_pipeline.py`、`plugins/entry/hub_fallback.py`（root）、`plugins/maintenance/fanout_reducer.py`（多处，含 `_decide_hub` 邻域喂 `estimate`/`render("decide_hub")`）、`plugins/maintenance/graph_summary.py`（root）、`diagnostics/graph_quality.py`、`mcs_agent/memory.py`（含 root）；实现时再次全量 grep 确认无遗漏。**结构性护栏（不靠纪律）**：提供 root 专用 helper（如 `store.root_children(universe)` 强制传参）或对 `get_out_hierarchy(SEED_ROOT_ID, universe=None)` 加告警 / 断言，使漏传在测试期暴露。无参默认仅旧库兼容（旧库单一 `"__reality__"`，返回全部 = 返回现实孤儿，行为等价）。

## 4. 查询 universe 上下文 + 跨 universe 查询工具（P7）

- [x] 4.1 `mcs/core/query_engine.py`：查询入口接受 `universe` 上下文参数；种子定位 / BFS 默认在该 universe 内进行（沿同 universe 边扩展）；root 的 `get_out_hierarchy` 调用传 universe。
- [x] 4.2 新增两个 agent 层（`mcs_agent`）跨 universe 工具：① **`get_cross_universe_edges`**（**只读**）——给定节点 + 目标 universe（或全 universe），经 store `get_cross_universe_edges` 取桥，带 `filter` / `pagination` / `limit` 受控返回（保 LLM 上下文不爆）；② **`link_cross_universe`**（**非 readonly**，概念桥唯一创建路径，方案 2）——给两端节点建普通 `关联` 边，护栏按 design D5：两端 universe MUST 不同、同对去重（已存 `关联` 不重建）、不触发合并、不加 label / 新边类型。两者均封装 store 既有 API（`get_cross_universe_edges` / `add_edge`），**store 层无新原语**。
- [x] 4.3 agent 工具表（`BUILTIN_TOOLS`）+ `DEFAULT_SYSTEM_PROMPT`：注册 **`get_cross_universe_edges`** + **`link_cross_universe`**，说明触发场景（agent 判定两节点是"同一实体的不同世界叙述"时显式建概念桥；其余单 universe 内查询不建桥）；**单 universe 工具（search / associate）带 `universe` 参数或从种子节点继承**（P7——默认 `"__reality__"`，agent 单 universe 查询不跨 universe）。

## 5. 测试（含边界，`.venv\Scripts\python.exe -m pytest -q`）

- [x] 5.1 universe 判定：无 `work_id` → `__reality__`；有 `work_id` → 该 id；判定不调 LLM。
- [x] 5.2 跨 universe 同名概念**不**合并（演义曹操 ≠ 正史曹操）。
- [x] 5.3 跨 universe 事实**不**判互斥（虚构 vs 真实字面冲突不互斥——核心收益验证）。
- [x] 5.4 同 universe 内仍正常合并 / 互斥（三国志 + 后汉书的曹操合并）。
- [x] 5.5 **摄入行为 event 即使 ingest 作品仍 `__reality__`**（不随作品变 universe）。
- [x] 5.6 同 universe 事件单向载重（核心不反查事件）+ 跨 universe 边双向过滤；`get_cross_universe_edges` 定向查可达。
- [x] 5.7 event 跨 universe 背书双向过滤（现实摄入 event 不把作品 fact 漏回活跃视图）。
- [x] 5.8 聚类 fanout 限同 universe（跨 universe 节点不被一起聚类）。
- [x] 5.9 虚拟根 `__seed_root__` 单根 + `universe` 参数**单侧过滤**（P8）：`get_out_hierarchy(root, universe="三国演义")` MUST 返回作品孤儿（**验 root→孤儿边跨 universe 仍单侧取回**，锁定 review 阻塞级修复）；`universe="__reality__"` 只返现实孤儿；无参返全部（旧库兼容）；普通节点 `get_out_hierarchy(A, universe=A.universe)` 恰等价两端同 universe。
- [x] 5.10 旧库迁移：无 `universe` 列的旧库打开 → 补列 + 全 `__reality__`（含事件节点）+ 行为等价。
- [x] 5.11 `Node` 不传 `universe` 默认 `__reality__`；`save_full` / `load` 多 universe round-trip 保真。
- [x] 5.12 半虚构契约：`work_id` 由提供方显式标注决定归属；无 `work_id` 一律 `__reality__`。
- [x] 5.13 agent 单 universe 查询不跨 universe（工具参数 / 种子继承，P7）。
- [x] 5.14 现有 mock / fixture 补 `universe` 字段（默认 `__reality__`），避免构造 / 调度报错。
- [x] 5.15 `link_cross_universe` 建概念桥（方案 2 唯一创建路径）：建后 `get_cross_universe_edges` 两端均可取回、`get_relations` 双向**仍**过滤（不漏进活跃视图）；同对去重（重复建不产第二条）；两端 universe 相同 MUST 拒绝；建桥**不**触发节点合并（两端各自保留）。
- [x] 5.16 **universe 元节点**（D6）：新 `work_id` ingest 自动建元节点（`node_class=概念`、`universe="__reality__"`）；成员 `universe` = 元节点 canonical id；框架 **MUST NOT** 自动建"成员 → 元节点"归属边（`get_out_hierarchy(元节点)` 不返成员）；元节点缺失时标量隔离仍工作。
- [x] 5.17 **归一**（D7）：work_id 别名命中复用 canonical（"三国"→"三国演义"元节点，不误裂）；未命中新建独立 universe（"三国志平话"，宁裂不并、不靠 LLM 自动并入）；注册表规范化不调 LLM；universe 合并默认不自动（需显式）。
- [x] 5.18 **get_subgraph BFS 不跨 universe**（review 第三泄漏点）：A（universe=X）经概念桥连 C（universe=Y），`get_subgraph(A)` 带 universe=X → 活跃子图 MUST 只含 X 节点、MUST NOT 经桥展开到 C。
- [x] 5.19 **get_related_events 跨 universe 背书亦返**（review 界定）：作品 fact 定向查 MUST 返回现实摄入背书事件（跨 universe），而同边 `get_relations(fact)` MUST 双向过滤。

## 6. 文档（保证代码与文档统一）

- [x] 6.1 `docs/graph-model-design.md`：§3.1 节点字段表增 `universe` + 段落（与 `node_class` 并列的归属轴、`__reality__` 默认、`work_id` 判定、全 `node_class` 含事件）+ **universe 元节点段（作品作为现实造物 vs 所述世界、不持成员、自动建）**；§3.3 载重双类过滤（同 universe 事件单向 / 跨 universe 双向）+ **get_subgraph BFS / get_related_events 界定（4 处过滤点）**；§5.1 ingest 增 universe 判定步骤（**经注册表规范化、未命中自动建元节点**、摄入 event 固定 `__reality__`）；§7 已知边界补"半虚构归属靠显式 `work_id`"、**"归一宁裂不并 / 别名登记 / universe 合并高门槛"**、"作品事件层 / 叙事时间线由 `work-narrative-events`"。
- [x] 6.2 `CLAUDE.md` 宪法：「节点 4 类」补 universe 归属维度 + **universe 元节点（现实造物 vs 所述世界、不持成员）**；铁律一不变量精确为“单 universe 内”；边方向载重规则补跨 universe 双向过滤；总体流程 ingest 补 universe 判定（**经注册表规范化、未命中自动建元节点**、摄入 event 固定 `__reality__`）。**顺手校正过时过渡说明**：现有代码已是统一图模型（`Node.node_class` / `Edge.type` 已落地），"现有代码仍是旧模型 / 迁移由该 change 跟踪"那段已不实，改为反映现状或删除。
- [x] 6.3 `openspec/specs/INDEX.md`：`unified-graph-schema` 行描述补 universe 维度。
- [x] 6.4 `docs/memory-agent.md`：工具表补跨 universe 查询工具 + 单 universe 工具的 universe 参数（P7）。

## 7. 验收

- [x] 7.1 `openspec validate multi-universe-graph --strict` 通过。
- [x] 7.2 `.venv\Scripts\python.exe -m pytest -q` 全绿。
- [x] 7.3 既有图（未带 universe）行为完全等价（回归：所有旧节点 / 事件默认 `__reality__`，合并 / 互斥 / 查询行为不变；现实摄入事件仍规则产生、`__reality__`）。
- [x] 7.4 review 3 点回归：`get_out_hierarchy` 单侧过滤（root→作品孤儿单侧取回）、`get_subgraph` BFS 不跨 universe、`get_related_events` 跨 universe 背书亦返——三者均有专测（5.9 / 5.18 / 5.19）且全绿。
