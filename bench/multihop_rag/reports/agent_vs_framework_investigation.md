# Agent vs 固定流程框架：MultiHop-RAG 检索调查报告

> 日期：2026-06-24　模型：deepseek-chat　图：`dschat_full_16k`（whole-doc 建图 609 篇，T=16K）
> 口径：同图、同 200 非-null query、同 lexical `doc_rerank`，逐题可比。
> 数据/脚本：`bench/multihop_rag/scripts/agent_full_run.py`（跑批）、`agent_case_study.py` / `closed_book_probe.py` / `agent_null_probe.py`（探针）；自动指标表见 [agent_vs_framework.md](agent_vs_framework.md)。

## 0. 问题

固定流程框架（种子定位 → 核心 BFS + 宽召回 `select_facts` → doc_rerank）在 MultiHop-RAG 上 hit@10 卡在 ~0.70。本轮验证一个假设：**以 agent 形式（deepseek ReAct，自带 search/associate/reason 导航工具）做检索，是否更好；好在哪、值不值。**

agent 的 `associate` 工具底层仍调框架同一条 BFS（`mcs.query(existing_context=...)`），唯一新增是 LLM 自主决定查什么、用哪个种子、何时停。

## 1. 总体结果（200 题，agent / 框架）

| 分组 | n | hit@10 | recall@10 | mrr@10 | recall@∞ | reached |
|---|---|---|---|---|---|---|
| **overall** | 200 | **0.825 / 0.695** | **0.537 / 0.388** | **0.604 / 0.468** | **0.890 / 0.730** | 0.955 / 0.925 |
| inference | 70 | 0.814 / 0.729 | 0.430 / 0.336 | 0.585 / 0.444 | 0.867 / 0.744 | 0.941 / 0.922 |
| comparison | 79 | 0.772 / 0.671 | 0.559 / 0.407 | 0.530 / 0.442 | 0.867 / 0.696 | 0.978 / 0.935 |
| temporal | 51 | 0.922 / 0.686 | 0.650 / 0.428 | 0.743 / 0.540 | 0.958 / 0.761 | 1.000 / 0.938 |

**agent 在召回与排序上全面胜出**：hit@10 +0.13、recall@10 +0.15、mrr@10 +0.14、recall@∞ +0.16；temporal 类差距最大。

> 指标说明：**reached** = gold 是否出现在检索集（任意名次，二元，导航天花板）；**recall@∞** = 全部 gold 召回比例（不限名次，完整召回率）；**hit@10/recall@10/mrr@10** = 前 10 名内的命中/召回/首命中倒数排名。`recall@∞ − recall@10` 即排序损失。

## 2. 召回 vs 排序的拆分（关键）

- **reached 仅 +0.03**（0.955 vs 0.925）：两边都能找到 ≥1 篇 gold（~95%）。
- **recall@∞ +0.16**（0.890 vs 0.730）：每题 2–4 篇 gold，**agent 把多篇 gold 捞得更全**——它把复杂问句拆成子实体/来源分别 keyword 定位种子，框架单种子 BFS 常只捞到其中一篇。
- **排序**：都召回到 gold 的题里，**gold 首篇平均名次 agent ~7 vs 框架 ~18**。候选文档池大小其实接近（agent 中位 191 vs 框架 232），所以不是"池子更小"，而是**池子更聚焦**——同一个 doc_rerank，agent 的节点集里 gold 词法上是主角、浮到前面；框架宽召回把旁支噪声也收进来、淹没 gold。

## 3. 排除"建图是瓶颈"（针对框架全漏的 15 题做建图侧审计）

对框架 hit@10 完全失败的 15 题、共 34 篇 gold 文档，按 source_tracking 反查图：

- **抽取**：34/34 有核心节点（每篇 4–85 个，中位 20.5）——无一抽空。
- **连通**：34/34 核心节点都有 `关联` 边（0 孤儿）。
- **跨文档整合**：32/34 与其它文档相连（仅 2 篇是冷门话题小孤岛）。

**结论：内容在图里、连通、可达——不是建图问题。** 这 15 题的失败是查询期种子定位漏的，正是 agent 能补的那环（agent 在 case 1 实测触达全部 3 篇 gold）。

## 4. Benchmark 完整性：闭卷泄漏探针

把 15 个差 case 的问题**不给图、纯让 deepseek 凭记忆答**：

- **yes/no 题 0/10**（全答 UNKNOWN，拒绝瞎猜）——这些问"某文章某日期的具体声明"，deepseek 正确地认识到没文档答不了。**MultiHop-RAG 的多文档+具体性设计有效，答案侧泄漏 ≈ 0。**
- **实体题 2/5**：Bettors（常识推理，非泄漏）、Everton（凭真实人物推断，唯一真世界知识泄漏）；Alameda Research 答成"FTX"（领域知道、精确答案错）。

**结论：agent 的胜利主体是正当检索，不是记忆作弊。** 实体推断捷径仅 1 例（Everton）吃到泄漏红利，且这条对私有语料会失效——泛化时打折。

## 5. null 诚实性探针

6 个 null_query（语料无答案，gold="Insufficient information."）：

- agent **从不"从图里幻觉"**（6/6 都诚实承认图里没有）。
- 但**真实 3 干净拒答 / 3 "承认图空后转用通用知识答"**（对封闭语料 RAG 口径 = 失败）。触发点是 deepseek **有把握的世界知识**（Sridevi/Vision Pro/Azure）；冷门具体事实它老实拒答。
- 根因是 agent 定位（记忆聊天助手，prompt 明写"通用知识正常答"），非 bug。要做严格封闭语料 RAG 需收紧 prompt（"图里没有就答 insufficient，禁用通用知识补"）。

## 6. 差 case 根因（200 题里 hit@10 失败的 12 题）

- **9/12 是排序**（召回到但排太深，主因跨语言词法弱：中文 content vs 英文 query）；**3/12 是没召回到**。
- **两个翻车极端**：① **早停/越界**——`20866502646f` 直接 0 工具、用参数知识答；`3d1803a7e9ed` 稳定 3 步早停。② **探爆**——`6aa1c570910a` 探 13 步 / 645 节点，gold 被淹到第 210 位。
- **非确定性**：同题两次跑会 win↔lose 翻面（`ed2bb96d847b`、`6aa1c570910a` 在小样本研究里 reached、全量跑里因探爆失败）。deepseek 采样随机 → 工具序列与节点数大幅波动。**逐类型小样本数字有真实噪声。**

## 7. 成本

- 总耗时 **4.0 小时**（200 题，均 73s/题）。
- agent 层 LLM 调用 779 次 + associate 内部 select_facts 扇出 3850 次 ≈ **23 次/题**（框架 ~21 次/题，仅多 ~10%）。
- agent 层 token **29.8M**（均 149K/题）——溢价主要在 ReAct 对话上下文滚雪球，非调用数。

## 8. 结论与建议

1. **agent 形式在这 200 题上确实更好**：召回（recall@∞ +0.16）+ 排序（hit@10 +0.13 / mrr +0.14）双赢。
2. **赢的是两个可低成本移植的杠杆，不是整套 agent**：
   - **查询拆解 → 多种子入口** → 提升召回（recall@∞）。
   - **聚焦候选集** → 提升排序（hit@10 / mrr）。
   整套 ReAct 的扩展层（associate 重跑 BFS + 上下文膨胀）对召回无额外贡献，只贡献 token 账单。
3. **deepseek 的隐患仍在**：早停/越界（8 题 agent 反输，含 0 工具直接答）、null 用参数知识兜、非确定性。任何"让 deepseek 自判够了就停/剪枝"的设计都要对冲它的过激。

## 复现

```bash
# agent 跑批（断点续跑 + 自动报告）
.venv/Scripts/python.exe -u bench/multihop_rag/scripts/agent_full_run.py
# 仅重生指标报告
.venv/Scripts/python.exe bench/multihop_rag/scripts/agent_full_run.py --report-only
# 探针
.venv/Scripts/python.exe bench/multihop_rag/scripts/closed_book_probe.py     # 闭卷泄漏
.venv/Scripts/python.exe bench/multihop_rag/scripts/agent_null_probe.py --n 6 # null 诚实性
```
