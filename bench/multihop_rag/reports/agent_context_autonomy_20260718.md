# agent-context-autonomy 评测总报告（2026-07-18）

> OpenSpec change `agent-context-autonomy` 的 multihop 200 题三臂对照：**基线**（无上下文管理，
> 2026-07-15 既有跑）/ **ctx 臂**（`context_budget=32000`，存根折叠 + pin + FINISH）/
> **USED 契约臂**（ctx + 收尾轮 + USED top-10 交付契约）。同 agent 图（`agent_build/graph.db`，
> 609 篇）、同 200 非-null query、同 lexical `doc_rerank` 评分。LLM=deepseek-chat，max_turns=8。
>
> 版本注记：ctx 臂前 169 题跑于收尾轮落地前（forced 返回兜底文本）、后 31 题含收尾轮；
> USED 契约臂全程新代码、5 分片并发（`--shard i/k`，每片独立图库副本）。
> 配套自动报告：`agent_context_autonomy_ab.md`（ctx vs 基线）、`agent_context_used_ab.md`
> （USED vs 基线）。

## 一、总表（200 题，overall）

| 臂 | reached | hit@2 | hit@4 | hit@10 | recall@10 | mrr@10 | recall@∞ | token/题 | LLM 调用/题 |
|---|---|---|---|---|---|---|---|---|---|
| 基线 | 0.880 | 0.535 | 0.660 | 0.795 | 0.528 | 0.537 | 0.805 | 127K | 3.7 |
| ctx | 0.930 | 0.545 | 0.610 | 0.780 | 0.505 | 0.535 | 0.873 | **85K** | 6.9 |
| **USED 契约** | **0.975** | **0.595** | **0.675** | **0.855** | **0.529** | **0.577** | **0.938** | 112K | 8.7 |

- **ctx 臂**：token **-33%**、reached **+5.0pt**；hit@10 -1.5pt（中段稀释：hit@2/mrr 持平、
  hit@4/recall@4 降——导航更全但词法排序消化不了，详见 §四）。
- **USED 契约臂全面最优**：对基线 reached **+9.5pt**、hit@10 **+6.0pt**、hit@2 **+6.0pt**、
  mrr@10 **+4.0pt**、recall@∞ **+13.3pt**，同时 token 仍 **-12%**。
  经济学结论：**折叠省下的 token 被证据配额驱动着再投入探索，同样的预算从"瞎花"变成"花在刀刃上"**。

## 二、分题型（reached / hit@10）

| 题型 | 基线 | ctx | USED 契约 |
|---|---|---|---|
| inference (70) | 0.843 / 0.729 | 0.843 / 0.671 | **0.971 / 0.900** |
| comparison (79) | 0.886 / 0.797 | 0.987 / 0.810 | 0.962 / 0.785 |
| temporal (51) | 0.922 / 0.882 | 0.961 / 0.882 | **1.000 / 0.922** |

最难的 inference 类被契约臂从全场最弱拉成最强（hit@10 0.729 → **0.900**，+17pt）；
temporal reached 满分；comparison 略低于基线（0.785 vs 0.797），是唯一的让步项。

## 三、终止行为（收尾轮 + 契约的效果）

| 终止类型 | ctx 臂 | USED 契约臂 |
|---|---|---|
| finish（主动收束） | 60 | 18 |
| finalized（收尾轮降级交付） | 19* | **156** |
| forced（无答案兜底） | 113* | **18** |
| implicit | 8 | 8 |

\* ctx 臂 169 题跑于收尾轮落地前，forced 大头是版本因素。

- ctx 臂曾暴露 **56% forced 丢答案**（超轮次门槛违规）；契约臂把无答案 forced 压到 **9%**，
  78% 的题走"探索到最后一刻 → 收尾轮强制交付"路径。
- 终止分桶质量（ctx 臂）：forced reached 0.991 / finish 仅 0.833——**过早自信收束才是质量短板**，
  证据配额正中要害（契约臂 reached 0.975 全场最高）。

## 四、排序侧结论（混合评分与遗留瓶颈）

- **词法 vs 混合口径在 200 题聚合上无差**（USED 引用采纳仅 24/200，混合评分退化为词法）。
  契约臂的增益主体来自**行为改变**（证据配额驱动更充分的探索）而非重排序。
- 中段稀释模式（ctx 臂）：hit@2 / mrr 持平、hit@4/recall@4-10 下降——multihop gold 是 2-4 篇一组，
  第 2/3 篇证据词法分弱、被更多触达文档挤出窗口。**词法 doc_rerank 仍是排序天花板**
  （与黄金笼、agent_build_20260715 结论一致）；USED 采纳率提上去后混合评分才有兑现空间。

## 五、上下文机制统计

| 项 | ctx 臂 | USED 契约臂 |
|---|---|---|
| 折叠 | 2108 | ~2900 |
| 逐出 / 拒注 | 0 / 0 | 0 / 0 |
| pin 采纳 | 1 | 少量 |
| 同参重发（盲目） | 117（117）/ 2483 调用 = 4.7% | 138（138）/ 3021 = 4.6% |
| USED 引用采纳 | 7/200 | 24/200 |

- **32K 预算全程未触发逐出/拒注**——折叠层单独就守住了预算（估算口径==发送口径硬闸生效、无一超限）。
- **pin 语义对 deepseek-chat 采纳失败**（全程个位数）：减脂收益全部来自不依赖模型配合的折叠层
  （设计上的"阶段 A 先行"判断正确）；盲目重复率口径因 pin 恒空而退化，仅作参考。
- USED 引用格式采纳率 12%，是下一个明确的改进杠杆（收尾轮指令强化 / few-shot）。

## 六、阶段门判定

| 门槛 | 结果 |
|---|---|
| token/题 降幅 ≥30%（阶段 A） | ✅ ctx 臂 -33%（契约臂 -12%，把节省再投质量） |
| reached 不降 | ✅ +5.0pt（ctx）/ +9.5pt（契约） |
| 超轮次失败不增 | ⚠️→✅ ctx 老版违规（0.56 丢答案）；收尾轮 + 契约后无答案 forced 9%，且这些题检索指标仍最高 |
| implicit 占比 | 0.04（两臂同），FINISH 约定遵从良好 |

> 范围注记：阶段门原文含黄金笼 30-50 题；本轮按用户指定跑 multihop 200（超出规模），
> 黄金笼口径未跑、留待需要时补测。

## 七、结论

1. **单一硬预算 + 模型自治工作集成立**：折叠层独立拿到 -33% token，reached 不降反升，
   硬闸零违规、零死锁。
2. **"重复遍历做成信号不做成机制"验证正确**：盲目重复仅 4.6%，同参标注 + 存根可见足以自律；
   积累集变化后的重看正是 agent 优于框架 BFS 的来源（recall@∞ +6.8pt）。
3. **收尾轮 + 交付契约是本轮最大意外收益**：给收束设证据配额（"凑不齐可信来源不许交卷"）
   同时治住了"过早自信收束"（质量）与"超轮次丢答案"（交付），三臂全面最优。
4. **排序仍是系统瓶颈**：导航侧 recall@∞ 已到 0.938，hit@10 天花板卡在词法 doc_rerank；
   USED 采纳率（12%）是把模型判断接进排序的下一个杠杆。
5. pin 语义在 deepseek-chat 上无采纳，机制保留（其他模型/后续调优），但不应作为收益预期。

## 八、复现

```bash
# ctx 臂（无契约）
.venv/Scripts/python.exe bench/multihop_rag/scripts/agent_full_run.py \
  --context-budget 32000 --graph-dir bench/multihop_rag/outputs/agent_build \
  --out-dir bench/multihop_rag/outputs/agent_build_full_run_ctx32k
# USED 契约臂（5 分片并发）
for i in 0 1 2 3 4; do
  .venv/Scripts/python.exe bench/multihop_rag/scripts/agent_full_run.py \
    --context-budget 32000 --used-contract --shard $i/5 \
    --graph-dir bench/multihop_rag/outputs/agent_build \
    --out-dir bench/multihop_rag/outputs/ctx32k_used200 &
done
# 报告
.venv/Scripts/python.exe bench/multihop_rag/scripts/ctx_ab_report.py \
  --ctx-dir bench/multihop_rag/outputs/ctx32k_used200 \
  --base-dir bench/multihop_rag/outputs/agent_build_full_run \
  --out bench/multihop_rag/reports/agent_context_used_ab.md
```

产出（gitignored）：`outputs/agent_build_full_run_ctx32k/`、`outputs/ctx32k_used200/`
（results\*.jsonl / graph.shard\*.db / run\*.log）。
