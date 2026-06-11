## 1. 存储层：单向边模型

- [x] 1.1 `mcs/core/store.py`：`StoreInterface.add_edge` 签名改为 `add_edge(source_id, target_id)`（去掉 `direction`）；更新 docstring 说明边一律单向、`get_neighbors` 返回出邻居
- [x] 1.2 `mcs/stores/in_memory.py`：`add_edge` 仅维护 `adjacency[source].add(target)`；`delete_edge` 只删 `(source,target)`；`_edge_key` 收敛为 `(source,target)`；`get_neighbors`==`get_out_neighbors`（均返回出邻居）
- [x] 1.3 `mcs/stores/sqlite_store.py`：边表 schema 去掉 `direction` 列（`(source_id, target_id)`）；同步 `add_edge`/`delete_edge`/`_edge_key`/`get_neighbors`/`get_out_neighbors`/`get_subgraph`
- [x] 1.4 `mcs/stores/sqlite_store.py`：`save_full`/`load` 适配新 schema，round-trip 逐条 `(source,target)` 保真；移除 `Edge.direction` 相关读写（或 `Edge` 数据类去掉 `direction` 字段，全仓引用同步）
- [x] 1.5 全仓 grep `direction=`、`bidirectional`、`get_out_neighbors`，逐处确认无遗漏的方向语义残留
  - 审查补充修复：`_absorb_hub_edges` 加反向边过滤排除语义出边；`cross_doc_linker` 补双向落边；空成员社区跳过

## 2. 写管线：语义边落两条单向

- [x] 2.1 `mcs/core/write_pipeline.py`：`_dispatch_create` 对每个 `edges_to` 锚点落 `add_edge(node, anchor)` 与 `add_edge(anchor, node)` 两条；篇内 `pending_named_edges` 同样落双向两条
- [x] 2.2 校验 `_apply_decisions` 不再依赖 `direction` 参数；新概念挂 `__seed_root__` 仍为单条下行 `root→concept`（`_maintain_seed_root` 内）

## 3. fanout_reducer 重写：主动守门 + 整窗单次裂变

- [x] 3.1 删除分批逻辑：移除 `_select_batch` 的贪婪取批分支与 `max_community_size` 截顶；移除 `_decide_hub` 的折半重试
- [x] 3.2 守门改主动：阶段 ⑤.5/⑥ 在邻域**即将超 T** 时即触发；`_compact_node` 改为"取中心 + 全部一跳子节点一次喂 `decide_hub`"，递归直到处处 ≤ T
- [x] 3.3 全局适用：`_has_budget_pressure`/触发逻辑覆盖任意超预算节点（不限 root）；保留对 root 的无条件挂概念逻辑
- [x] 3.4 重连改纯下行：`_reorganize` / `_reorganize_multi` 对每条有效 `(hub H, 成员 M)` 执行 删 `C→M`、建 `C→H`、建 `H→M`；**删除上行边 `M→C` 的建立**
- [x] 3.5 hub 来源：保留三策略（合并同义 / 提拔已有子节点为 hub / 新建概括 hub）；提拔即置 `role="hub"`；幻觉 id（关联目标不存在）忽略；未关联成员留在 C 下
- [x] 3.6 合并同义：`_merge_synonyms` 适配单向边迁移（被合并节点的两条语义边迁到代表节点，去重 + 防自环）
- [x] 3.7 修接受判据：`_validate_reorg` 的 `before`/`after` 都按中心节点**全邻域**同口径估算；仅 `after < before` 落地，否则回滚（修掉 before 仅算一批的口径错）
- [x] 3.8 骨架识别改 role：`_absorb_hub_edges` 及任何"枚举 hub / 判定层级"处改读 `role=="hub"`，不再依据边方向
- [x] 3.9 移除 `_guard_new_hubs`/`_maintain_seed_root` 里与分批、上行边、`direction` 相关的死代码

## 4. 导航与查询：沿全部单向出边

- [x] 4.1 `mcs/plugins/entry/hub_fallback.py`：下钻候选由"仅 out 邻居"改为节点的**全部出边目标**（`get_neighbors`）；保留 `visited`+`max_depth` 防环
- [x] 4.2 `mcs/core/query_engine.py`：`_locate_seeds`/`_traverse` 的邻居获取确认走单向 `get_neighbors`；扩展可达性不依赖旧双向语义
- [x] 4.3 `mcs/core/context_renderer.py`：如渲染/估算涉及 `direction` 处同步（铁律一口径不变）

## 5. 规范与文档同步

- [x] 5.1 CLAUDE.md：改"边方向"段（"层级有向、语义双向"→"全单向，语义=两条对向单向边、层级纯下行无上行"）；改总体流程（`judge_relations` 落两条边）；守门描述改"主动、不分批、全局"
- [x] 5.2 `openspec/specs/architecture.md`：边模型（单向）、存储 schema、导航语义更新（若该 spec 涉及）
- [x] 5.3 复核本 change 三份 spec delta 与最终实现一致（apply 后归档前再校验一遍）

## 6. 数据重建、回归与评测

- [x] 6.1 删除作废的 `bench/multihop_rag/outputs/v4flash_full/*.db`（旧库含 bidirectional/上行边/退化扁平 root）
- [x] 6.2 跑 `.venv\Scripts\python.exe -m pytest -q`，修复因边模型/方向断言变化的用例（store/fanout/seed-graph/导航相关）
- [ ] 6.3 用建图脚本从零重建小规模图，体检：root 及各节点扇出分布、裸概念占比、`decide_hub` 覆盖率、是否处处 ≤ T、无 `bidirectional` 残留
- [ ] 6.4 多跳评测对比改造前后召回/精度，确认"语义边参与导航"非负向；若漂移明显，按 design Open Questions 评估加"导航优先级 / 扇出数硬上限 N"
