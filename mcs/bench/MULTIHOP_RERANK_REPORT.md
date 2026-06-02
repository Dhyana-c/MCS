# MultiHop-RAG 检索重排评测报告

**日期**：2026-06-02
**数据**：MultiHop-RAG（`yixuantt/MultiHop-RAG`），200 篇文档子集（seed=42），**418 个可达 query**（117 非 null + 301 null）
**图**：`multihop_bench.db`（4380 节点 / 2901 边；一次建图、reload 复用，不重建）
**指标口径**：文档级检索召回——`query()` 返回的节点经 `source_tracking` 映射回来源文档（`doc_id` = 文档 title），与 gold `evidence_list` 的来源文档比对。`null_query`（语料无答案）不计入 Hit@k/MAP/MRR，单独报 `avg_docs_retrieved`。

> 数据来源口径：baseline 取自最早 build+query 同进程跑（候选召回 86%）；节点级 / 文档级取自 **reload 修复后**跑（候选召回 86%）。三者 **overall 非 null（n=117）同口径可比**。

---

## 摘要

在同一张已建图上对比三种检索后处理：

- **baseline**：`query()` 节点按 rank 序映射文档（不重排）
- **节点级重排**（`--rerank`，核心 `query_postprocess` 插件）：对 `query()` 返回的**节点**打词法分重排
- **文档级重排**（`--doc-rerank`，bench 专用、不改核心）：对节点映射出的**候选文档**直接打词法分重排

**核心结论**：文档级重排把 overall **recall@10 从 0.140 推到 0.503（3.6×）**，是节点级 0.226 的 **2.2×**；**hit@10 0.726、mrr@10 0.509**。inference 类 **hit@10 达 100%**、recall@10 0.885（进入离线 POC 0.81 区间）。两个深层 bug 修复后，418 query **零失败**。

---

## 1. 三方对比（overall，117 非 null）

| 指标 | baseline | 节点级 `--rerank` | **文档级 `--doc-rerank`** | 文档级 / baseline |
|---|---|---|---|---|
| recall@2 | 0.009 | 0.110 | **0.303** | ~34× |
| recall@4 | 0.033 | 0.161 | **0.376** | ~11× |
| **recall@10** | 0.140 | 0.226 | **0.503** | **3.6×** |
| hit@2 | 0.017 | 0.239 | **0.547** | ~32× |
| hit@4 | 0.077 | 0.291 | **0.632** | ~8× |
| **hit@10** | 0.265 | 0.350 | **0.726** | 2.7× |
| **mrr@10** | 0.049 | 0.231 | **0.509** | ~10× |
| **map@10** | 0.027 | 0.135 | **0.331** | ~12× |

（低 k 的倍数因基数极小而偏大，看绝对值更直观。）

## 2. 按 question_type（recall@10 / hit@10）

| 类型 | n | baseline | 节点级 | **文档级** |
|---|---|---|---|---|
| **inference** | 13 | 0.000 / 0.000 | 0.500 / 0.846 | **0.885 / 1.000** |
| **comparison** | 76 | 0.103 / 0.224 | 0.184 / 0.276 | **0.434 / 0.645** |
| **temporal** | 28 | 0.304 / 0.500 | 0.214 / 0.321 | **0.512 / 0.821** |

- **inference**（纯多跳推理）提升最猛：baseline 全 0 → 文档级 **hit@10 100%**、recall@10 0.885，呼应离线 POC「inference 从全 0 → 0.88@10」。
- comparison / temporal 也大幅提升，但绝对值低于 inference，是拉低 overall 的短板。

## 3. null query 诊断

| | n | avg_docs_retrieved |
|---|---|---|
| baseline | 301 | 163.8 |
| 文档级（`top_n=0` 不截断） | 301 | 164.3 |

null query 召回宽集；文档级 `top_n=0` 不截断 → 候选文档数与 baseline 持平（仅重排序）。要抑制 null 撒网可设 `--doc-rerank-top-n`。

## 4. 候选集召回（无视排名）

文档级 418 跑：非 null **候选集召回 0.863**、**失败 0%**。即 gold 文档 **86% 已进候选集**——剩下纯粹是排名问题，正是重排要解决的。

---

## 5. 关键发现：文档级 vs 节点级的粒度

评测指标是**文档级**，但 MCS 的 `query()` 返回**节点**。「节点级排序 → 节点→文档映射」会**稀释/错位**：文档名次由它第一次出现的节点决定，未必是该文档最相关的代表；hub 节点跨多文档、词法分高时还会把无关文档顶上来。

**文档级重排**直接对候选文档打分（排序对象 = 评测对象 = 文档），绕过这层稀释——这就是 recall@10 从节点级 0.226 翻倍到 0.503 的根因。

## 6. 过程中修复的两个深层 bug

评测暴露并修复了两个让「reload 复用图」实际坏掉的 bug：

1. **reload 后索引未重建**：`AliasIndexPlugin` 在空图上建索引、load-on-startup 后没重建 → reload 后 alias 种子定位全失效 → 候选集召回从 86% 崩到 **7%**。修复（`_try_load_from_storage` 重建 `IndexInterface` 索引）后候选召回恢复，是文档级跑出 0.503 的前提。
2. **navigate_hub 解析脆弱**：LLM 不规整输出（截断 / `JSON:` 前缀 / 对象数组）一失败就抛异常拖垮整条 query → 计 miss。改为**宽容解析**（兼容各形态、解析不出返回 `[]`）后，418 query **零失败**。

## 7. 距 POC 0.81 的差距分析

overall recall@10 0.503 vs POC 0.81：

- **候选召回上限 86%**：14% 的 gold 文档没进候选集（图遍历到达范围受限），词法重排救不回。
- **词法对真·多跳有限**：桥接文档可能不含查询词、词法分不够。
- inference 类已达 0.885（进入 POC 区间）；comparison / temporal 是主要短板。

## 8. 后续方向

1. **文档文本用 corpus 原文**（`title + body`）替代当前「召回节点聚合文本」（design D2 扩展点）——信息更全，预计再提升。
2. **嵌入 / LLM 文档级打分器**——接住「桥接文档不含查询词」的真·多跳（comparison / temporal）。
3. **提升候选召回**（图连通性 / 遍历到达范围）——突破 86% 上限（属 `graph-construction-quality` research change）。

---

## 附：复现命令

```bash
# baseline（节点 rank 序映射文档）
python -m mcs.bench.multihop_rag --corpus-subset 200 --db ./multihop_bench.db --output ./mh_baseline
# 节点级重排
python -m mcs.bench.multihop_rag --corpus-subset 200 --db ./multihop_bench.db --rerank --rerank-top-n 0 --exclude-null --output ./mh_node
# 文档级重排（本报告 · 418 全量）
python -m mcs.bench.multihop_rag --corpus-subset 200 --db ./multihop_bench.db --doc-rerank --doc-rerank-top-n 0 --output ./mh_doc
```
