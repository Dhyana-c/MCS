# MultiHop-RAG 评测最终报告

> 本轮：deepseek-chat + unified-graph-schema（4类节点/2类边/双层）+ whole-doc 建图 609 篇，T=16K。
> 聚焦：查询召回/排序优化。所有结果基于同一张已收敛图（`dschat_full_16k/graph.db`，db 已保留可重测）。

## 一、结果总表（hit@10 / recall@10，200 query 除非另注）

| # | 方案 | hit@10 | recall@10 | 说明 |
|---|---|---|---|---|
| 1 | alias_entry（jieba 词面） | 0.230 | 0.117 | 停用词噪声淹 gold |
| 2 | hub_fallback（navigate_hub） | 0.170 | 0.088 | 逐层贪婪选错 hub |
| 3 | 实验 B（root 子节点 BFS，旧 prompt） | 0.550 | 0.298 | 全 hub 并发，定天花板 |
| 4 | **实验 B + 新 prompt（宽召回）** | **0.695** | **0.388** | **本轮最大改进 +0.145** |
| 5 | LLM 重排（分组，material 27K bug） | 0.690 | 0.473 | 召回涨、hit 持平（过载） |
| 6 | 只要事实 + 分组 rerank（20q） | 0.500 | 0.600 | 召回崩（"只概念文档"gold 漏） |
| 7 | 方案 A 排节点不分组（20q） | 0.600 | 0.950 | 召回恢复、排序单位错 |

分类型（方案 4，新 prompt 200q）：inference 0.743 / temporal 0.686 / comparison 0.671。

## 二、关键发现链（逐层排除，定位根因）

1. **种子定位是入口瓶颈**：同图同 BFS，alias 0.23 / hub 0.17 / 实验 B（全种子）0.55——种子给全给准，hit@10 翻倍。图质量、BFS、select_facts 召回能力都不是瓶颈。
2. **select_facts 旧 prompt 对 comparison 系统性空返回**：控制变量实锤——同 query 同 prompt，大候选（188/31K 字符）LLM 返回空、gold 全漏；缩到 14 候选 LLM 准确选中。根因是 prompt「优先直接回答 + 若无相关返回 []」对比较题诱导空。改宽召回（涉及查询任一实体即纳入 + 至少 top-K）→ comparison 0.367→0.671。
3. **doc_rerank `aggregate_docs` 跨文档放大 bug**：accumulated ≤16K（受 T 约束，实装符合 spec），但按文档分组把跨文档节点重复展开，material 放大到 27K（放大 1.7× = 平均跨文档数），LLM 过载。`_format_doc_candidates` 截断 200 字符是「先放大再截断」的矛盾补丁。
4. **词法排序弱的根因是跨语言**：节点 content 是建图时 LLM 生成的**中文**摘要，query 是**英文** → body 词法交集近零，hit@10 主要靠标题（英文∩英文）。反事实：body 换英文原文 → 0.840（零 LLM）。
5. **LLM 重排排节点不如排文档**：方案 A 排节点（hit 0.60）< 排文档（0.69）。评测单位是文档，节点序→文档序映射有损耗 + 「最多选 15」限制漏 gold 文档。

## 三、已吸收的修改（保留）

- **`mcs/prompts/select_facts.py` 宽召回 prompt**：SYSTEM/USER 改宽召回口径（涉及查询任一实体即纳入、至少 top-K、去掉「返回 []」诱导）。验证 0.55→0.695（+0.145），单测 130 passed。**核心改进，确定吸收。**

## 四、已回滚的修改（不吸收）

- **`bench/plugins/doc_rerank.py` llm_doc_rerank 方案 A**（直接排节点）：hit 0.60 < 词法 0.69，回滚到分组版。doc_rerank 重排设计留给后续（见 proposal）。

## 五、待办（下轮）

1. **proposal: `separate-accumulate-frontier`**（已立）——解耦积累集/遍历集，frontier 宽探索 + accumulated 精筛输出，从结构上治跨文档放大 + 排序候选爆炸。
2. **跨语言**：建图 content 改英文（与 query 同语言），词法 body 命中恢复，反事实 0.84、零 LLM。是最强杠杆，但要重建图。
3. **读写分离**（task #31）：`select_facts`（读，宽召回）与写侧 `query_nodes` 关联定位（应精准）当前共用 prompt，推广到重建图前须分离。

## 六、结论

- **框架核心健康**：gold 召回 0.89+（全节点），图模型 / 不变量 / 双层 / BFS 召回链路全部验证通过，不是瓶颈。
- **hit@10 卡在排序**（下游 bench `doc_rerank` + 跨语言），非 MCS 核心 bug。
- **本轮最大收益**：select_facts 宽召回 prompt（+0.145），一行核心逻辑没动、零 embedding、单测全绿。
- **下一杠杆**：结构上解耦积累集/遍历集（proposal）+ 跨语言对齐（content 英文）。
