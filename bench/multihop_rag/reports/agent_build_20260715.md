# MultiHop-RAG 纯 agent 建图评测报告（2026-07-15）

> 用 ReAct agent（learn/search/merge/split，通用循环 `bench/agent_build.py`）重建
> MultiHop-RAG 全量 609 篇共享图，跑同一套 200 个非-null query（agent 导航查询），
> 与「框架图 + agent 查询」「框架图 + 框架查询」两条既有基线**同 query 集、同
> lexical doc_rerank 评分**三方对照。LLM=deepseek-chat，T=16000。

## 一、建图（agent，609 篇全量）

| 项 | agent 图（agent_build） | 框架图（dschat_full_16k，对照） |
|---|---|---|
| 文档 | 609/609（0 失败、0 强制补写） | 607 |
| 规模 | 16289 节点 / 51529 边 | 13201 节点 / 43230 边 |
| 耗时 | 10.9h（均 65s/篇，断点续跑 3 段） | —（早期构建） |
| agent 行为 | 全部自主调 learn；4 篇经 agent 重试吸收 parse 失败；部分篇写后主动 search 复查；0 次 merge/split（保守 prompt） | 无 agent 层 |

**建图期健壮性实测**（1009 次抽取/关系 LLM 调用）：998 次干净解析、10 次 JSON
格式坏（未转义 ASCII 引号/漏逗号，salvage 救回、丢约 10 个对象）、1 次流中断截断、
12 次彻底 parse 失败**全部被 agent 层 learn 重试吸收**（框架 build 里同类失败 =
整篇跳过丢弃）——agent 建图的 ReAct 循环提供了框架路径没有的逐篇重试韧性。

## 二、检索指标三方对照（同 200 非-null query、同 doc_rerank）

| 组合 | hit@2 | hit@10 | recall@10 | mrr@10 | reached | recall@∞ |
|---|---|---|---|---|---|---|
| **agent图 + agent查**（本次） | 0.535 | 0.795 | 0.528 | 0.537 | 0.880 | 0.805 |
| 框架图 + agent查 | 0.615 | **0.825** | 0.537 | 0.604 | **0.955** | 0.890 |
| 框架图 + 框架查 | 0.465 | 0.695 | 0.388 | 0.468 | 0.925 | 0.730 |

分类型 hit@10：

| 组合 | inference (70) | comparison (79) | temporal (51) |
|---|---|---|---|
| agent图 + agent查 | 0.729 | 0.797 | 0.882 |
| 框架图 + agent查 | 0.814 | 0.772 | 0.922 |
| 框架图 + 框架查 | 0.729 | 0.671 | 0.686 |

## 三、结论

1. **查询方式是第一杠杆**：agent 导航查询在两张图上都大幅优于框架固定 BFS
   （hit@10 0.795/0.825 vs 0.695；temporal 提升最大 0.686 → 0.88+）——与黄金笼
   评测结论一致（导航能力强、排序仍是词法 doc_rerank 瓶颈：hit@2 明显低于 hit@10）。
2. **agent 建的图整体略逊框架图**（同 agent 查询下 hit@10 0.795 vs 0.825，
   reached 0.880 vs 0.955，差距集中在 inference 类 0.729 vs 0.814）。两者同为
   whole-doc 单次 ingest，抽取管线代码存在版本差（框架图为早期构建），且 agent 图
   节点更多（+23%）但触达率更低——提示碎片化/对齐差异，**归因需要受控重建实验**
   （同版本代码分别跑两种建图），本报告不下定论。
3. **agent 建图的净收益在健壮性而非指标**：0 篇丢弃（框架路径会丢 parse 失败篇）、
   逐篇重试、写后自检——指标差距若经受控实验确认为版本差而非路径差，agent 建图
   可作为默认路径。

## 四、成本

| 阶段 | 耗时 | agent 层 | MCS 内部 |
|---|---|---|---|
| 建图 609 篇 | 10.9h | ~1300 次调用 | extract/judge 等若干 |
| 查询 200 题 | 2.5h（45s/题，均 4.4 工具/题） | 733 次 / 25.4M token（127K/题） | select_facts 扇出 3078 次 |

## 五、评测暴露并已修复的核心问题（均带回归测试）

1. **alias 毒化链**：建图期 LLM 偶发把 `aliases_to_add` 写成对象（如
   `{"target_name": "CMC"}`），写入无规范化 → 毒化 4 个节点 → 查询启动时
   `AliasIndexPlugin.build` 在 unhashable dict 上崩、**load-on-startup 吞异常后带着
   残缺索引静默运行**（关键词检索报废）。已修三层：judge_relations 解析收口
   list[str] / `_dispatch_merge` 写入闸门 / alias_index 读取跳过 + 反序列化自愈；
   图内 4 节点已修复。
2. **`agent_case_study.CapturingMemory` 旧签名**：multi-universe-graph 加 universe
   轴后未跟上，对现行 `MemoryStore` 必炸（TypeError）；已同步签名。
3. **LLM JSON 模式**（根治建图期 10 例 JSON 语法失误）：`PromptBundle.json_output`
   声明 + DeepSeek `response_format=json_object`（写管线抽取三件套开启）+ 解析器
   单键包装容忍。本次建图/查询使用修复前代码（保持与基线可比）；后续构建生效。

## 六、复现

```bash
# agent 建图（断点续跑）
.venv/Scripts/python.exe bench/multihop_rag/scripts/agent_build.py
# 200 case（agent 图）
.venv/Scripts/python.exe bench/multihop_rag/scripts/agent_full_run.py \
  --graph-dir bench/multihop_rag/outputs/agent_build \
  --out-dir bench/multihop_rag/outputs/agent_build_full_run
```

产出（gitignored）：`outputs/agent_build/`（graph.db / build_log.jsonl）、
`outputs/agent_build_full_run/`（results.jsonl / metrics_agent.json / AGENT_REPORT.md）。
