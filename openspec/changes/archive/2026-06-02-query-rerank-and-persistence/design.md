## Context

MultiHop-RAG 评测（200 篇共享图、117 条非 null query）给出了硬数据：MCS 的语义游走**能召回** gold 文档（无视排名总召回 86%、95.7% 命中≥1），但 `query()` 返回的是**无序宽集**（gold 中位 rank 36 / ~165 篇），导致 Hit@10 只有 0.27。零成本离线词法重排 POC（同候选集）把 recall@10 **0.14→0.81**——证明**排名是唯一卡点**，且一个简单 reranker 即可解决。

同时评测暴露 3 个真持久化 bug：① `source_tracking` 被 `json.dumps(default=str)` 存成字符串、`load()` 不反序列化 → reload 后检索全空；② `_run_persist` 不自己 commit、靠下一块顺带刷 → 滞后一块、shutdown 丢最后一块；③ `IdempotencyCheckPlugin` 在 preprocess 就标记块已摄入 → 出错的块被标记完成、续跑留空洞。这三个让"图落盘复用/续跑 query"实际是坏的。

## Goals / Non-Goals

**Goals:**
- 新增 `query_postprocess` reranker 插件，把 `query()` 输出按查询相关性过滤+排序+截断
- 打分器可插拔：词法 baseline（零成本、已验证）+ 预留嵌入/LLM
- 修持久化三件套，让"落盘→reload→检索/续跑"可靠 round-trip
- 让现有 `multihop_bench.db`（已建好的图）可被 reload 复用，零成本验证 reranker

**Non-Goals:**
- 图构建质量（跨文档链接增强、CommunityMerger 社区检测/合并、有向/带类型边）—— 开放式研究，**另立 change**（POC 已证它不是本检索指标的根因）
- 不追 SOTA；嵌入/LLM 打分器为后续增强
- reranker 默认 **opt-in**，本 change 不改默认插件链的既有行为

## Decisions

### D1: reranker 作为 query_postprocess 插件（零 core 改动）

实现 `PostprocessPluginInterface`、`position="query_postprocess"`。`process(nodes, ctx)` 从 `ctx.user_input` 拿查询，给每个 node 打分、过滤低分、按分降序、截断 top-N，返回重排后的 `List[Node]`。`_run_postprocess` 已支持链式调用，无需改 core。

### D2: 打分器接口可插拔，先词法 baseline

定义 `Scorer` 协议 `score(query: str, node: Node) -> float`。首版实装 **LexicalScorer**：查询与 `node.name`/`content`/statements 的 token 重叠，name/标题加权（POC 已证有效、零额外 LLM 调用）。预留 `EmbeddingScorer` / `LLMScorer`（后续增强，接同一接口）。

**理由**：词法零成本即可验证架构与收益；语义打分（嵌入/LLM）能接住"桥接文档不含查询词"的真·多跳，留作增强。

### D3: 节点级打分 → 文档级指标的传导

插件在**节点级**重排；bench 的 `retrieved_docs` 按 node 顺序映射到文档 → 重排后 gold 相关节点靠前 → 其来源文档靠前。

**风险与缓解**：hub 节点（横跨多文档）若打高分会"灌"多文档；但查询相关的通常是具体节点而非泛 hub。必要时 bench 侧叠加一层**文档级**重排兜底（按 query 相关性给候选文档打分，POC 即此口径）。

### D4: 默认 opt-in

reranker 通过配置开关启用，不进 phase-1 默认链，避免影响既有行为与现有评测基线。验证收益后再单独决定是否默认开启。

### D5: 序列化保真 round-trip

`sqlite_storage.save_node` 持久化 `extensions` 时，对带编解码的 NodeExtension（如 source_tracking）走插件的 `serialize()`（产出 dict），而非 `json.dumps(default=str)`；`load()` 对应走 `deserialize()`（或在使用侧容忍）。**向后兼容**：`load`/反序列化 MUST 同时容忍历史的字符串化 `Source(...)` 格式（正则抽 `doc_id` 等），使现有 `multihop_bench.db` 不需重建即可复用。

### D6: 提交时序——_run_persist 自己 commit

`_run_persist` 在 save_node/save_edge 后显式 `commit()`，每次 ingest 落定。消除"滞后一块 + shutdown 丢最后一块"。

### D7: idempotency 改 mark-on-success（与 D6 一起才彻底）

去重**检查**仍在 preprocess（读 `document_chunks` 判重）；但**写入标记**移到该块成功落盘之后（与节点持久化同时机/同事务），保证"标记已摄入 ⇔ 节点已落盘"，续跑不留空洞、出错的块会被重试。

### D8: 为何排除图构建质量

连通性差（34% 孤立、1681 碎片、跨文档边仅 634）与 CommunityMerger 未实现是真的，但 POC 证明 gold 仍进候选集（召回 86%）→ **不是本指标根因**，只是让候选网偏宽。其修法（社区检测、跨文档链接、有向/带类型边）是开放式研究、收口慢，与本 change 的高确定性修复混在一起会拖累交付，故另立 research change。

## Risks / Trade-offs

- **[节点级 vs 文档级粒度]** 见 D3 → 缓解：必要时 bench 侧叠加文档级重排
- **[词法打分对真·多跳有限]** 桥接文档可能不含查询词 → 缓解：POC 余量极大（0.14→0.81）先兑现；嵌入/LLM 打分器作增强
- **[历史 db 兼容]** 现有 `multihop_bench.db` 里 source 是字符串 → 缓解：D5 的反序列化向后兼容，避免重建那张 ¥110 的图
- **[idempotency 时序联动]** D7 改动若与 D6 不一致会再次产生"标记≠落盘" → 缓解：两者必须一起改、同时机
- **[reranker 过滤过狠]** 阈值太高会误杀 → 缓解：阈值/top-N 可配置，默认保守（只排序+宽松截断，不激进过滤）