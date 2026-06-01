## Context

建图成本是 MCS 规模化的主要障碍（¥110 主要是 200 篇 build）。代码确认的三个驱动：① 阶段②每块都跑完整多轮 LLM 查询（`write_pipeline.py:113`，super-linear）；② 压缩每块触发；③ 前缀缓存命中仅 3%。

纪律：**先 instrument 量化每块/每 purpose 的真实花费，再以"假设→对照实验→度量"逐项验证优化**，且任何优化**不得劣化图质量**（用 `graph-construction-quality` 的连通性诊断作护栏）。

## Goals / Non-Goals

**Goals:**
- 建图成本 instrumentation：按 purpose/阶段统计 token 与调用，定位大头、做回归基线
- 修正 dry-run 成本模型（含建图 super-linear + query 阶段），让预估可信、跑时可设上限
- 验证并落地 1–2 条高 ROI 优化（首选阶段②轻量化），净省 token 且不劣化连通性

**Non-Goals:**
- 不做 reranker/持久化（query-rerank-and-persistence）；不做社区合并等质量增强本身（graph-construction-quality）
- 不以牺牲图质量换成本（连通性诊断是硬护栏）
- 嵌入/LLM 高级优化在定型前不硬 commit

## Decisions

### D1: instrumentation 与真实 dry-run 先行

先做"每 purpose/阶段 token 计量"和修正后的 dry-run。任何优化都用它度量增量，杜绝凭感觉改。这也兑现"跑前可预见、跑时实时盯+硬上限"的成本纪律。

### D2: 阶段②轻量化是首选杠杆，但必须双重验证

把锚点定位从完整 LLM 查询循环换成轻量检索（先试现有 `alias_index`，不够再上嵌入）。**双重门槛**：成本 instrumentation 证明净省 + 连通性诊断证明不劣化（理想是两边都赢——嵌入可能比早停的 LLM 游走召回更多锚点）。

### D3: 压缩延后用"批量模式"开关

加一个 bulk/deferred compaction 模式：批量 build 时跳过每块压缩，build 结束统一跑一次。默认行为不变（opt-in），避免影响增量 ingest 语义。

### D4: 优化全部 opt-in + 实验门槛

每项优化先做成开关，在 50–100 篇小图上开/关对照，度量"省多少 token + 连通性是否劣化"，达标才考虑进默认。

### D5: 复用而非新造护栏

连通性护栏直接用 `graph-construction-quality` 的诊断；不另造。两 change 共用阶段②代码，需协同推进。

## Open Questions

- **阶段②**：alias_index 够不够找到好锚点？还是必须上嵌入？嵌入模型选型（本地 sentence-transformer vs API）与其自身成本？
- **帮还是伤**：轻量锚点定位对连通性是净增益还是损害？（假设两边都赢，需实验证伪）
- **压缩延后**：批量末尾统一压缩，与逐块压缩的最终图质量/正确性是否等价？
- **前缀缓存**：prompt 重排实际能把命中率从 3% 提到多少？省多少 input 成本？
- **嵌入预筛**：judge_relations 用嵌入预筛，精度/召回够不够、能省多少 LLM 调用？
- **协调**：本 change 的阶段②改动与 graph-construction-quality 的阶段②改动如何不打架（谁先做、共用一套开关？）

## Risks / Trade-offs

- **[省钱伤质量]** 阶段②轻量化降低锚点质量→图更碎 → 缓解：连通性诊断硬护栏，不达标不落
- **[嵌入引入依赖/成本]** 嵌入模型本身有成本与选型负担 → 缓解：先试零依赖的 alias_index，不行再上轻量本地嵌入
- **[压缩延后改变语义]** 批量末尾压缩可能与逐块结果不等价 → 缓解：opt-in + 小图对照验证等价性
- **[与 graph-construction-quality 改动冲突]** 共用阶段②ize代码 → 缓解：协同排期、共用开关、统一用连通性诊断验证
- **[优化收益不及预期]** 某项实测省得不多 → 缓解：instrumentation 先行，允许"结论是不做某项"