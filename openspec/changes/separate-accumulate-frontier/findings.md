# separate-accumulate-frontier 双角色诊断发现

> 6 case（3 comparison + 3 inference）× 5 版 deepseek prompt + GLM-5.1 V4，验证
> frontier/accumulated 解耦在真实 LLM 上的效果。图：`dschat_full_16k`，T=16000。
> 诊断脚本：`bench/multihop_rag/scripts/diag_dualrole.py`（monkey-patch `_traverse`/`llm.call`）。

## 几版结果对比

| 版本 | LLM | prompt 特征 | gold 命中 | accumulated（非空） | select_facts |
|---|---|---|---|---|---|
| V1 | deepseek | 双角色初版 | 2/6 | 33–160 | 少 |
| V2 | deepseek | 禁空 + result 偏宽 | 3/6 | 91–364 | 中 |
| V3 | deepseek | + 拿不准归 result | 4/6 | 69–325（≈230，胀） | 多（q3 154） |
| V4 | deepseek | 删拿不准（双角色） | 3/6 | 10–267（<230） | 中 |
| V5 | deepseek | 单列表+背景（同源） | 2/6 | 11–256 | 少 |
| **V4** | **GLM-5.1** | **双角色** | **5/6** | **16–78** | 中 |

## 核心结论

1. **双角色设计正确**：GLM-5.1 V4 达 gold 5/6 + accumulated 精筛 16–78——正是双角色
   理想态（result 严、frontier 宽）。query 4（SBF/FTX）从 deepseek 的 0/3 救到 3/3。
2. **deepseek 两难是能力问题**：五版 result 口径调不出两全（严→空漏 gold、宽→膨胀）。
   GLM 守住双角色 prompt 证明非设计缺陷，是 deepseek-chat 对"双角色 JSON + 禁空"指令
   的遵守不稳定（曾 75.7% 调用返回裸 `[]`）。
3. **query 6（OpenAI）顽固空**：多版 gold 0，select_facts 几次就早停——种子定位
   （阶段②）没给到 foothold，与 select_facts prompt 无关，需单独查 `_locate_seeds`。
4. **性能瓶颈**：解耦后 frontier 不吃 T、只受 `max_frontier_nodes=500`，扇出大 →
   select_facts 次数涨（V3 q3 154 次）。旧同源时 frontier=accumulated 受 `used_tokens`
   隐式约束、自然收敛；解耦切断了这条链条，frontier 获得独立自由度（"宽探索"必需），
   代价是必须手动约束，而 500 不和 T 挂钩、设太大。

## 建议

- **双角色（V4）作 change 设计定稿**（GLM 验证正确）。当前 `select_facts.py` 即 V4 双角色版。
- **生产换 GLM 或更强模型**；deepseek-chat 受限（双角色两难 + 部分 query 空返回）。
  deepseek 上若必须用，V3（拿不准归 result，gold 4/6）或 V4（精筛，gold 3/6）二选一。
- **性能**：`max_frontier_nodes` 500→150；或 frontier 按 token 软预算（与 T 挂钩，
  恢复"自然收敛"）；或 frontier 按相关度截 top-K 入队。
- **查 query 6 种子定位**（`_locate_seeds` 为何没展开）——独立于 prompt 的真漏召回根因。

## 附：GLM 网关备注

GLM-5.1 经智谱官方网关（open.bigmodel.cn）对 query 1（Epoch Times）/ 3（Buffalo）偶发
敏感内容审查（code 1301）；经 0ki.cn 网关未触发。生产选网关需注意审查差异。
