## Context

节点级 reranker（已归档 `query-rerank-and-persistence`）把 gold **节点**排到前面（mrr/map 提升 4-5×），但传导到**文档级**指标只到 recall@10 0.226——候选集召回已 86%、离线 POC 文档级却到 0.81。瓶颈在「节点级排序 → `retrieved_docs` 节点→文档映射」：文档的名次由它**第一次出现的节点**决定，而那个节点未必是该文档最相关的代表；hub 节点跨多文档、词法分高时还会把无关文档顶上来。本 change 在**评测侧**加一层文档级重排，直接对候选文档打分排序，量化文档级收益。

约束（来自需求）：**bench-only、放 `mcs/bench/` 下、不改 mcs 核心、不进默认 query 插件链**。

## Goals / Non-Goals

**Goals:**
- 评测侧**文档级重排**：把 `query()` 召回节点映射成候选文档，对每篇文档按 query 相关性直接打分、过滤、排序、截断，产出最终 `retrieved_docs`。
- 打分**复用词法思路**（token 重叠 + 标题加权，零额外 LLM 调用），与节点级 reranker 同口径，便于公平对比。
- `multihop_rag.py` 加 `--doc-rerank` 开关，默认 opt-in。
- 量化 文档级 vs 节点级 vs baseline 的 Hit@k/MAP/MRR，验证能否往 POC 0.81 推。

**Non-Goals:**
- **不**改 mcs 核心（`core`/`plugins`/`interfaces`）、**不**做 `query_postprocess` 插件、**不**进默认链。
- 不追 SOTA；嵌入/LLM 文档级打分器留作后续增强。
- 不改既有评测基线（默认不启用时行为不变）。

## Decisions

### D1: 放 bench 侧、不进核心
文档级重排实现为 `mcs/bench/doc_rerank.py` 的纯函数（无插件生命周期、无 PluginManager），由 `multihop_rag.py` 在 `retrieved_docs` 处调用。**理由**：需求明确「只给测试集用」；文档级粒度本就是评测口径（gold 是文档），不属于 MCS 核心「返回 `List[Node]`」的契约；放 bench 侧零侵入、不影响核心节点级 reranker。

### D2: 文档级文本 = 标题 + 该文档下召回节点的聚合
对每篇候选文档，文本 = `doc_id`（即文档 title）+ 该文档下**本次被召回的节点**的 `name`/`content`/statements 聚合。**理由**：只用图内召回信息、自洽轻量；一篇文档若有多个相关节点被召回，聚合后相关性更强、比单节点更能代表文档。**备选**：用 corpus 原文（`MultiHopDoc.title+body`）信息更全——留作可选增强（D2 的扩展点），首版先用节点聚合。

### D3: 词法打分复用、零 LLM
打分沿用节点级 `LexicalScorer` 思路：query 与文档级文本的 token 重叠、标题（`doc_id`）加权。把 token 化逻辑抽成 bench 可复用的小工具（或直接复用 `mcs/plugins/phase1/rerank.py` 的 tokenize），避免重复实现。**理由**：与节点级同口径才公平对比；零额外 LLM 调用、近乎零成本验证。

### D4: `--doc-rerank` 独立于 `--rerank`，作用于全召回候选文档
文档级重排取 `query()` 返回节点（**不依赖**是否开节点级 `--rerank`）映射出的**候选文档全集**再排序，避免被节点级 `top_n` 截断稀释。最干净的三方对比：baseline（节点原序映射）/ `--rerank`（节点级）/ `--doc-rerank`（文档级）。**理由**：文档级要在尽量全的候选文档上排序才能发挥；与节点级正交便于归因。

### D5: 默认 opt-in
不传 `--doc-rerank` 时 `retrieved_docs` 与现状完全一致。**理由**：不动既有评测基线。

## Risks / Trade-offs

- **[词法对真·多跳有限]** 桥接文档可能不含查询词 → 缓解：POC 余量极大（0.14→0.81）先兑现；嵌入/LLM 文档打分器作后续增强（同接口可替换）。
- **[文档文本来源]** 节点聚合可能信息不全（只含被召回节点）→ 缓解：D2 预留 corpus 原文扩展点；首版节点聚合 + 标题已足够验证收益。
- **[hub 节点跨多文档引入噪声]** 一个高分 hub 节点的 source 会分到多篇文档，给每篇都灌入其文本 → 缓解：聚合以标题加权为主、文档独有节点优先；必要时对 hub 节点降权。
- **[与节点级 reranker 的边界]** 两者都叫「重排」易混 → 缓解：文档级仅 bench-only、命名 `doc_rerank`、文档/开关明确区分（节点级=核心 `query_postprocess`，文档级=评测层）。
