# MultiHop-RAG 检索评测报告（dual-edge · 全量 608/609 篇 · deepseek-chat）

**日期**：2026-06-14
**数据**：MultiHop-RAG（`yixuantt/MultiHop-RAG`），whole_doc 整篇摄入
**模型**：deepseek-chat（建图 + 查询 + 文档级重排同模型）
**token_budget T**：16000（建图守门 + 查询子图同阈值）
**边模型**：dual-edge（层级边 + 事实边，事实边存一份两端索引）
**库**：`bench/multihop_rag/outputs/chat_16k/graph.db`

---

## 1. 图状态（608/609 篇）

| 项 | 值 |
|---|---|
| 已建文档 | 608 / 609（1 篇 extract_concepts JSON 截断，已加 salvage 兜底，可重试补回） |
| 节点 | **10,639**（概念去重后；去重前 12,822，hub 159） |
| 边 | **20,344**（层级 + 事实；去重重定向后从 20,929 折叠） |
| 概念去重 | 合并 1,220 组、删 **2,183** 个同名重复节点（Amazon 18→1），`source_tracking` 已 union |
| fanout 口径不变量（中心+层级子节点 ≤ T） | ✓ 全过 |
| 重复事实边（同 src+tgt+label） | 24（去重补丁上线前的老残留，全程零新增；0.13%） |

> 建图阶段曾出现 21 篇瞬时 ingest 失败（概念多的列表型文档），重试后恢复到 608/609；
> 另清理 339 条无意义 label 事实边（修掉假热点 Danny Elfman 339→1）。

## 2. 检索质量

### 主结果：doc_rerank=llm · 全量 608 篇图（概念去重后）· 200 query

| 类型 | n | hit@2 | hit@4 | **hit@10** | recall@10 | map@10 | mrr@10 |
|---|---|---|---|---|---|---|---|
| **overall** | 200 | 0.580 | 0.655 | **0.770** | 0.484 | 0.315 | 0.551 |
| inference | 70 | 0.529 | 0.600 | 0.743 | 0.415 | 0.240 | 0.480 |
| comparison | 79 | 0.595 | 0.658 | 0.734 | 0.458 | 0.336 | 0.569 |
| temporal | 51 | 0.627 | 0.725 | **0.863** | 0.618 | 0.386 | 0.620 |

可达 query（gold 全落在已建图内）2253；本次取前 200 评测。temporal 最强（0.863）。

### 概念去重 before/after（同配置：608 图 · llm · 同 200 query）

| 指标 | 去重前 | **去重后** | Δ |
|---|---|---|---|
| hit@10 | 0.695 | **0.770** | **+0.075** |
| recall@10 | 0.417 | **0.484** | **+0.067** |
| map@10 | 0.294 | 0.315 | +0.021 |
| mrr@10 | 0.525 | 0.551 | +0.026 |

合并 2,183 个同名重复节点（同实体的事实 + `source_tracking` 归并到 canonical）后，全类型 hit@10 上升（inference +8.6、comparison +8.8、temporal +3.9）。**代价**：热点节点变胖，200 query 耗时 43min→74min（~1.7×）→ 指向下一步的"事实视图压缩"。

### 参照：doc_rerank=lexical · 200 篇子图 · 100 query

| 指标 | hit@2 | hit@4 | hit@10 | recall@10 | map@10 | mrr@10 |
|---|---|---|---|---|---|---|
| overall (n=100) | 0.73 | 0.82 | **0.91** | 0.644 | 0.436 | 0.706 |

> 200 篇子图干扰少、偏易；不能与全量直接比，仅作"子图上检索逻辑健康"的参照。

### 与历史基线对比

| 配置 | 图规模 | hit@10 | recall@10 |
|---|---|---|---|
| 历史（lexical doc_rerank, T=32k, 1000q） | 全量 609 | 0.649 | 0.438 |
| **本次（llm doc_rerank, T=16k, 200q, 去重后）** | 全量 608 | **0.770** | 0.484 |

dual-edge + 本轮全部修复（含概念去重）在全量上**明显超过历史参考**（hit@10 0.770 vs 0.649，+12pts）。注意配置不同（rerank 类型、T、样本量），非严格同条件。

## 3. 成本

| 项 | 值 |
|---|---|
| 单条查询遍历输入 | ~114k token（200 篇子图时 ~72k → 全量更大，**成本随语料增长**） |
| 200 query 遍历侧 | ~¥45（现价 miss ¥2/M）/ ~¥23（夜间半价） |
| llm doc_rerank | 每条 +1 次调用，总耗时仅 ~13s/条（比 lexical 多 ~1–3s），开销不大 |
| 耗时 | 200 query：去重前 2583s（~43min）/ **去重后 4463s（~74min，~1.7×）**——去重把同实体事实堆到 canonical 热点上、视图变胖 |

> **关键成本修复**：查询侧 `accumulated_summary`（每次 select_facts 重发全部已累积节点的 name+content）原占输入 ~73%，改为"仅 name + 限最近 N"后单次调用输入 18,750→4,094 token（**~4.6× 降本**），查询提速近一倍。

## 4. 本轮修复汇总（dual-edge 相关）

| # | 修复 | 影响 |
|---|---|---|
| 1 | `_rollback_reorg` 经 `store.snapshot/restore` 保边 id + 还原变更跟踪 | 修掉 SQLite 增量持久化在 fanout 回滚后边翻倍的污染 |
| 2 | `_traverse` 改批量分层（select_facts 富余合并 + 解析失败逐节点回退） | 符合 spec MUST 场景，减少调用数 |
| 3 | 事实边去重（`add_edge` 按 src+tgt+label） | 多文档断言同一命题不再产生重复边 |
| 4 | `accumulated_summary` 修剪（仅 name + 限最近 N） | 查询输入 ~4.6× 降本 |
| 5 | 节点级重排 `top_n` 可关（默认不截断/放全量） | 召回/命中提升 |
| 6 | judge_relations / extract_concepts JSON 截断 salvage（逐元素 raw_decode） | 概念多的文档不再整篇丢弃 |
| 7 | 无意义 label 过滤（「无关/无直接关系/无…关系」否定族）+ 清理存量 339 条 | 修掉"假热点"（Danny Elfman 339→1），事实图去污染 |
| 8 | 概念精确同名合并（写入期 `_merge_concept_into` 守门 + 存量清理 1220 组/2183 节点） | **hit@10 +7.5、recall@10 +6.7**（同实体事实/来源归并到 canonical） |

## 5. 已知问题 / 下一步

1. **事实视图压缩（当前最该做）**：概念去重把同实体事实堆到 canonical 热点上 → 视图更胖、查询 ~1.7× 慢（单条遍历随语料/去重增长）。方向："同 label 事实星渲染期折叠成 gist + lazy 属性、按需展开"（纯视图层，不动存储 / D2）——**既降本又能稳住去重拿到的召回**。
2. **lexical vs llm 干净对照缺失**：需要时在去重图上补跑 lexical-608。
3. 1 篇 extract_concepts 失败已有 salvage 兜底，重试可补回 609。

> 概念去重已完成（见 §1、§2 before/after、§4 #8）：hit@10 0.695 → **0.770**。

## 附：复现命令

```bash
# 建图（续跑/幂等，缺失补建）
python bench/multihop_rag/scripts/build.py --docs 609 --token-budget 16000 \
    --output bench/multihop_rag/outputs/chat_16k

# 查询评测（doc_rerank 默认 lexical；本报告主结果用 llm）
python bench/multihop_rag/scripts/test.py \
    --output bench/multihop_rag/outputs/chat_16k --queries 200 --doc-rerank llm

# 建图+评测一条龙
python bench/multihop_rag/scripts/eval.py --docs 609 --queries 200 \
    --token-budget 16000 --output bench/multihop_rag/outputs/chat_16k --doc-rerank llm
```
