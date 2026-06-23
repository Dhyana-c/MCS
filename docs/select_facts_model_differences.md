# select_facts 双角色 prompt 的模型差异与多版本实验

> `separate-accumulate-frontier` change 在 `select_facts` 双角色解耦上的真实 LLM 实验记录。
> 6 case(3 comparison + 3 inference),图 `dschat_full_16k`,T=16000。
>
> **一句话结论:双角色设计正确——GLM-5.1 验证(gold 5/6 + accumulated 精筛 16-78);
> deepseek-chat 守不住精细口径,只能宽召回 + 禁空兜底。**

## 1. 背景

`select_facts`(查询阶段③ 事实 BFS)改为双角色输出 `{result, frontier}`:
- `result`(和查询有关)→ `accumulated`(吃 T、为返回集)
- `frontier`(和查询可能有关)→ BFS 队列(不吃 T、驱动多跳探索)

目标:解耦"探索召回口径"(宽)与"进 LLM 输出口径"(严),`accumulated` 不被宽召回绑架。

## 2. 核心模型差异

| 维度 | deepseek-chat | GLM-5.1 |
|---|---|---|
| 守双角色 JSON 格式 | 不稳(曾 75.7% 返裸 `[]`) | 稳 |
| result 口径拿捏 | 两难(严→空漏 gold、宽→膨胀) | 准(result 严 + frontier 宽) |
| 禁空指令遵守 | 弱(窄召回/可空→全空) | 强 |
| V4 双角色 gold | 3/6 | **5/6** |
| accumulated 精筛 | 10–267(不稳) | **16–78(稳)** |

**deepseek 的两难是能力问题,不是设计问题。** GLM 守住 prompt 即证明。

## 3. 多版本 prompt 实验(每版:要点 / 为什么 / 效果 / 适用)

### V1 双角色初版(无禁空/下限)
- **要点**:result 严、frontier 宽,无禁空约束。
- **为什么**:最初设计,信任 LLM 守口径。
- **效果**:gold 2/6、accumulated 33–160(空多)。deepseek 大规模空返回(75.7% 返 `[]`)。

### V2 禁空 + result 偏宽
- **要点**:加"绝不返回空" + result 口径放宽。
- **为什么**:救 V1 的空返回。
- **效果**:gold 3/6、accumulated 91–364(部分胀)。

### V3 拿不准归 result(最宽 + 禁空)
- **要点**:"拿不准归 result" + 禁空 + 硬性下限(候选≥3 → result≥1、frontier≥3)。
- **为什么**:反 deepseek 保守倾向,强保 accumulated 非空。
- **效果**:**gold 4/6(deepseek 最优)**、accumulated 69–325(胀,q3 跑 154 次 select)。
- **适用**:**deepseek 生产推荐**(接受 accumulated 胀,配下游 rerank 收敛)。

### V4 删拿不准(双角色 + 背景,定稿)
- **要点**:删"拿不准归 result",LLM 自然判有关/可能有关 + 任务背景说明。
- **为什么**:V3 胀,试精筛;加背景让 LLM 理解多跳检索语境。
- **效果**:deepseek gold 3/6、accumulated 10–267;**GLM-5.1 gold 5/6 + accumulated 16–78(全局最优)**。
- **适用**:**强模型(GLM/Claude)生产推荐**。**当前 `select_facts.py` 读侧 = V4**。

### V5 单列表宽召回 + 背景(同源,不区分角色)
- **要点**:回退单列表(选中即 accumulated+frontier 同源)+ 背景说明。
- **为什么**:试简单单列表能否避开双角色复杂度。
- **效果**:gold 2/6、accumulated 11–256(BFS 早停,召回崩)。
- **适用**:不推荐(双角色目标落空,且 deepseek 召回崩)。

### 窄召回 + 背景(可空)
- **要点**:单列表窄召回(选最相关、**可空**)+ 背景。
- **为什么**:试窄召回 + 背景能否精筛。
- **效果**:**gold 0/6(灾难)**、5/6 全空 accumulated。deepseek 对"可空"极度敏感。
- **适用**:**禁用**(deepseek 灾难)。

## 4. deepseek 铁律

deepseek-chat 在 `select_facts` 上:
1. **必须禁空 + 宽召回**——口径越严/越可空,gold 越崩(窄召回 0/6 < V5 2/6 < V4 3/6 < V3 4/6)。
2. **守不住双角色 JSON**——曾 75.7% 返裸 `[]`(经 `coerce_select_result` 归一为"两者双空")。
3. **result 两难无解**——严→空漏 gold、宽→accumulated 胀。最优是 V3(拿不准归 result,gold 4/6,但 accumulated 胀 ~230)。

**deepseek 生产**:V3(宽召回+禁空+拿不准归 result),接受 accumulated 胀;或换 GLM 用 V4。

## 5. GLM-5.1 优势

1. 守双角色 JSON 稳。
2. result 口径拿捏准(严精筛 + 宽探索并存)。
3. V4 gold 5/6 + accumulated 16–78——双角色理想态。
4. **网关注意**:GLM 经智谱官方网关(open.bigmodel.cn)对部分 query(Epoch Times / Buffalo)有敏感审查(code 1301);经 0ki.cn 网关未触发。生产选网关需注意审查差异。

**GLM 生产**:V4(双角色),accumulated 精筛 + gold 高。

## 6. 多版本 prompt 保留策略

代码 `mcs/prompts/select_facts.py` 读侧定稿 **V4**(双角色,适配强模型)。其余版本记录于本文档,按模型/场景切换(切换 = 改 SYSTEM/USER 文本,版本文本见 git 历史或本文档要点):

| 场景 | 推荐版本 | 理由 |
|---|---|---|
| 强模型(GLM/Claude) | **V4 双角色** | 精筛 accumulated + 高 gold |
| deepseek-chat | **V3 拿不准归 result** | gold 4/6(deepseek 最优),accumulated 胀靠下游 rerank 收 |
| 不要用 | 窄召回 / V5 单列表 | deepseek 灾难(0/6)/ 召回崩(2/6) |

## 7. 性能备注(独立于模型)

解耦后 frontier 不吃 T、扇出大 → select_facts 次数涨(V3 q3 154 次;GLM V4 q5 也标 frontier 8748)。两个模型都有。
优化:`max_frontier_nodes` 500→150 / frontier 按 token 软预算(与 T 挂钩)/ frontier 按相关度截 top-K。详见 `openspec/changes/separate-accumulate-frontier/findings.md`。

## 8. 复现

```bash
# deepseek(当前读侧 prompt = V4;要跑 V3 等先改 SYSTEM/USER 文本)
MCS_DIAG_LLM=deepseek .venv/Scripts/python.exe bench/multihop_rag/scripts/diag_dualrole.py

# GLM-5.1 经 0ki.cn 网关(避开智谱官方网关的敏感审查)
ANTHROPIC_BASE_URL=https://api.0ki.cn/api/anthropic \
ANTHROPIC_AUTH_TOKEN=<token> \
ANTHROPIC_MODEL=GLM-5.1 \
MCS_DIAG_LLM=claude \
.venv/Scripts/python.exe bench/multihop_rag/scripts/diag_dualrole.py
```
