# Agent vs 固定流程：MultiHop-RAG 评测报告

> 同图 `dschat_full_16k`，同 200 个非-null query，同 lexical `doc_rerank` 评分。
> agent = deepseek-chat ReAct（search/associate/reason 导航），框架 = 固定 BFS + select_facts。
> 框架基线取自 `dschat_full_16k_bfsroot_newprompt`，仅对比 agent 已跑的 200 题。

## 一、总体指标对照（agent vs 框架）

| 分组 | n | hit@10 (a/框) | recall@10 (a/框) | mrr@10 (a/框) | recall@∞ (a/框) |
|---|---|---|---|---|---|
| overall | 200 | 0.825 / 0.695 | 0.537 / 0.388 | 0.604 / 0.468 | 0.890 / 0.730 |
| inference_query | 70 | 0.814 / 0.729 | 0.430 / 0.336 | 0.585 / 0.444 | 0.867 / 0.744 |
| comparison_query | 79 | 0.772 / 0.671 | 0.559 / 0.407 | 0.530 / 0.442 | 0.867 / 0.696 |
| temporal_query | 51 | 0.922 / 0.686 | 0.650 / 0.428 | 0.743 / 0.540 | 0.958 / 0.761 |

**召回天花板 reached（gold 是否出现在检索集中，任意名次）**：agent **0.955** vs 框架 **0.925**。
> reached 衡量「导航到没到」（与排序无关）；hit@10 衡量「排没排进前 10」。两者差距即排序损失。

## 二、成本

- 总耗时 **4.0 小时**（200 题，均 **73s/题**）
- agent 层 LLM 调用 **779** 次；associate 内部 select_facts 扇出 **3850** 次
- agent 层 token **29.8M**（均 149K/题）
- 粗算每题 LLM 调用 ≈ 23 次（agent 层 + 内部扇出）

## 三、reached 对照分桶

- **agent 捞回（框架漏、agent reached）**：14 题
- **agent 反而丢（框架 reached、agent 没）**：8 题 → ['20866502646f', 'c7c2e37b08c7', '188ca65e68af', '4e22c21d0fc5', '1df7f41db713', 'b203b5299476', '34dbe3e37821', '371de003b0e9']
- **两边都漏**：1 题 → ['3d1803a7e9ed']

## 四、关键背景（前序实验已确认）

- **agent 赢在选入口**：LLM 把复杂问句拆成多个子实体/来源，分别 keyword 定位种子；associate 底层仍是同一条框架 BFS。可移植为单次 `QUERY_PREPROCESS`，不必整套 ReAct。
- **建图不是瓶颈**：15 个框架全漏 case 的 gold 文档 34/34 抽出且连通（32/34 跨文档整合）。
- **泄漏小**：闭卷探针 10/10 yes-no 题 deepseek 答 UNKNOWN，实体题仅 1 例（Everton）吃到世界知识红利。
- **null 风险**：6 个 null case 中 3 例 agent「承认图里没有后转用通用知识答」（封闭语料口径=失败），需 prompt 收紧。

## 五、结论

- agent 在召回/导航上比固定流程 高 3.0 个点（reached 0.955 vs 0.925）。
- 代价是数量级更高的 LLM 调用/token（见成本）。增益主体可低成本移植（查询拆解），整套 agent 的扩展层对召回无额外贡献。
- hit@10 看排序：reached 提升能否转化为 hit@10，取决于 doc_rerank（跨语言词法弱，见既有 REPORT）。
