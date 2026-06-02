## 1. 文档级重排核心（`mcs/bench/doc_rerank.py`）

- [x] 1.1 节点→文档反向聚合：把 `List[Node]` 按 `source_tracking` 的 `doc_id` 分组，聚合每文档的文本（`doc_id` 标题 + 该文档下召回节点的 `name`/`content`/statements）
- [x] 1.2 文档级词法打分：查询与文档级文本的 token 重叠、标题加权（复用/抽取 `rerank.py` 的 tokenize 思路，零额外 LLM 调用）
- [x] 1.3 `doc_rerank(nodes, query, top_n, min_score) -> list[str]`：聚合→打分→过滤低分→按分降序→截断 top-N；空召回/无 `doc_id` 返回 `[]`
- [x] 1.4 配置项：`top_n`、`min_score`（保守默认）；预留打分器替换位（嵌入/LLM，仅占位/文档）

## 2. multihop 评测集成（`mcs/bench/multihop_rag.py`）

- [x] 2.1 加 `--doc-rerank` 开关 + `MultiHopEvalConfig` 字段 + CLI（独立于 `--rerank`）；可配 `--doc-rerank-top-n`
- [x] 2.2 在 `retrieved_docs` 处接入：启用 `--doc-rerank` 时对召回节点走 `doc_rerank` 产出文档列表
- [x] 2.3 旁路：未启用时 `retrieved_docs` 与现状完全一致（默认 opt-in，不改基线）

## 3. 测试（`tests/test_bench_doc_rerank.py`）

- [x] 3.1 测试节点→文档聚合：构造已知节点验证分组与文档级文本拼装
- [x] 3.2 测试文档级打分 + 重排/过滤/截断：构造已知文档验证顺序与 top-N
- [x] 3.3 测试空召回 / 无 `doc_id` 透传返回 `[]`
- [x] 3.4 测试默认 opt-in：未启用时 `retrieved_docs` 与现状一致
- [x] 3.5 测试与节点级 `--rerank` 正交组合（runner 层 mock 验证）

## 4. 验证（在现有图/结果上，近乎零成本）

- [x] 4.1 复用已建 `multihop_bench.db`（reload 已修），`--doc-rerank` 重跑 query 阶段（117 非 null，候选召回 0.863、失败 0%）
- [x] 4.2 对比 **baseline / 节点级 `--rerank` / 文档级 `--doc-rerank`** 的 Hit@k/MAP/MRR（117 非 null，同口径）
- [x] 4.3 记录提升幅度；与节点级 recall@10 **0.226**、离线 POC **0.81** 对照
      —— 文档级 recall@10 **0.477**（节点级 2.1×、baseline 3.4×）、hit@10 0.718、mrr@10 0.501。距 POC 0.81 的剩余差距主因：候选召回 86%（14% 漏召）+ 词法对真·多跳有限；进一步可试 corpus 原文/嵌入打分（design D2）。

## 5. 文档

- [x] 5.1 更新 `mcs/bench/MULTIHOP_RAG.md`：说明 `--doc-rerank`、文档级 vs 节点级重排的区别与 verify 流程
