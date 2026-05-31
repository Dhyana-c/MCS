## 1. Reranker 插件（query_postprocess）

- [ ] 1.1 定义打分器接口 `Scorer.score(query: str, node: Node) -> float`
- [ ] 1.2 实装 `LexicalScorer`：查询与 `node.name`/`content`/statements 的 token 重叠，name/标题加权（零额外 LLM 调用）
- [ ] 1.3 实现 `RerankPlugin`（`PostprocessPluginInterface`，`position="query_postprocess"`）：`process(nodes, ctx)` 用 `ctx.user_input` 打分→过滤低分→按分降序→截断 top-N
- [ ] 1.4 配置项：启用开关（默认 opt-in）、top_n、阈值、scorer 选择；注册进 plugin registry
- [ ] 1.5 预留 `EmbeddingScorer` / `LLMScorer` 接口位（不实装，仅占位/文档）

## 2. 序列化保真 round-trip

- [ ] 2.1 `sqlite_storage.save_node`：对带编解码的 NodeExtension（source_tracking 等）走插件 `serialize()` 产出 dict，替换 `json.dumps(default=str)`
- [ ] 2.2 `sqlite_storage.load`：对应走 `deserialize()` 还原结构化记录
- [ ] 2.3 向后兼容：`load`/反序列化容忍历史字符串化 `Source(...)`（正则抽 `doc_id` 等），使现有 db 可复用
- [ ] 2.4 round-trip 自检：save→load 后 `extensions["source_tracking"]["sources"]` 为 dict/Source、可取 `doc_id`

## 3. 提交时序 + idempotency mark-on-success

- [ ] 3.1 `write_pipeline._run_persist`：save_node/save_edge 后显式 `commit()`，每次 ingest 落定
- [ ] 3.2 `IdempotencyCheckPlugin`：去重检查留在 preprocess（读 `document_chunks`），但**标记写入**移到块成功落盘之后
- [ ] 3.3 确保"标记已摄入 ⇔ 节点已提交"一致（与 3.1 同时机）；中断未落盘的块续跑会重试

## 4. bench 质量（顺带收口）

- [ ] 4.1 hotpot `extract_supporting_facts`：按 node rank 取 top-N 剪枝（缓解过度预测）
- [ ] 4.2 hotpot `dry_run`：换成实测 token 模型（~90K/条），替换旧的 7900
- [ ] 4.3 multihop 加 `--exclude-null`（CLI + config + 加载/聚合时排除 null_query）

## 5. 测试

- [ ] 5.1 测试 LexicalScorer 打分 + RerankPlugin 重排/过滤/截断（构造已知节点验证顺序）
- [ ] 5.2 测试默认 opt-in：未启用时 `query()` 行为不变
- [ ] 5.3 测试序列化 round-trip：save→load 后 source 为 dict、可取 doc_id
- [ ] 5.4 测试向后兼容：喂字符串化 `Source(...)` 也能还原 doc_id
- [ ] 5.5 测试提交时序：独立连接能读到刚 ingest 的节点；shutdown 不丢最后一块
- [ ] 5.6 测试 idempotency mark-on-success：出错的块未被标记、续跑重试
- [ ] 5.7 测试 hotpot top-N 剪枝 与 multihop `--exclude-null`

## 6. 验证（在现有图上，近乎零成本）

- [ ] 6.1 reload 现有 `multihop_bench.db`（修完 2.x 后 source 可用），确认 `retrieved_docs` 非空
- [ ] 6.2 启用 reranker 重跑 query 阶段（不重建图），对比修复前后的 Hit@k/MAP/MRR
- [ ] 6.3 记录提升幅度；与离线 POC（recall@10 0.14→0.81）对照

## 7. 文档

- [ ] 7.1 更新 `mcs/bench/MULTIHOP_RAG.md`：说明 reranker 开关、verify 流程
- [ ] 7.2 在 `PENDING_FIXES.md` 勾掉本 change 覆盖的项；图构建质量另立 research change 的占位说明
