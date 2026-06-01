## 1. 数据获取与加载

- [x] 1.1 编写数据获取说明（从 HuggingFace `yixuantt/MultiHop-RAG` 下载 `multihoprag_corpus.json` + `multihoprag_qa.json`），见 `mcs/bench/MULTIHOP_RAG.md`
- [x] 1.2 实现 `MultiHopDoc` / `MultiHopQuery`（+`Evidence`）dataclass（doc: title/body/source/published_at/url/author/category；query: query/answer/question_type/evidence_list）
- [x] 1.3 实现加载器：读取 corpus + queries；路径缺失时抛 FileNotFoundError 并提示下载
- [x] 1.4 实现 corpus 子集采样 + query 同步过滤（只保留 evidence 来源文档全在子集内的 query）

## 2. 共享图构建（build-once）

- [x] 2.1 实现 `chunk_body()`：按段落切块、过长段落再按句子切、截断到 max_chunks、首块前置标题
- [x] 2.2 实现 `build_shared_graph()`：创建**一个** MCS 实例（`sqlite_storage.path=<db_path>`，非 `:memory:`），逐文档逐块 `ingest()`，传 `doc_id=title/chunk_id/section_title` 元数据
- [x] 2.3 idempotency 跳过：重复构建时已摄入文档块不重复消耗（依赖现有 idempotency_check）
- [x] 2.4 load-on-startup 复用：同 db_path 再建实例时复用已落盘图（依赖现有机制）

## 3. 查询→证据映射

- [x] 3.1 实现 Node→来源文档映射：从 `extensions["source_tracking"]["sources"]` 取 doc_id（多来源取并集）
- [x] 3.2 实现 `retrieved_docs()`：按 node rank 去重的来源文档有序列表
- [x] 3.3 实现 query 的 gold 证据文档集合提取（`MultiHopQuery.gold_doc_titles`）

## 4. 检索指标

- [x] 4.1 实现 `recall_at_k` / `hit_at_k`（top-k 召回率 + 命中率）
- [x] 4.2 实现 `map_at_k` / `mrr_at_k`（文档级排名）
- [x] 4.3 实现 null_query 单独诊断（排除出召回统计，报平均返回文档数）
- [x] 4.4 实现 `aggregate_metrics()`：按 question_type（inference/comparison/temporal）+ overall 分组

## 5. 评测运行器

- [x] 5.1 实现 `MultiHopEvalConfig` dataclass
- [x] 5.2 实现 `MultiHopEvalRunner.run()`：加载+过滤 → 构建共享图 → 逐 query 检索+映射 → 计算指标
- [x] 5.3 实现两层断点续跑：ingest 靠 idempotency；query 按 query_id（query 文本 hash）进度跳过
- [x] 5.4 实现检索结果增量落盘 + UTF-8 安全输出
- [x] 5.5 实现 dry-run：用实测 ~9K token/段 模型预估首建图 token 与费用
- [x] 5.6 实现指标输出（终端摘要 + metrics.json）

## 6. CLI 入口

- [x] 6.1 实现 `mcs.bench.multihop_rag:main()` CLI
- [x] 6.2 支持 `--corpus`, `--queries`, `--corpus-subset`, `--llm`, `--db`, `--output`, `--k`, `--max-chunks`, `--no-resume`, `--dry-run`
- [x] 6.3 （可选，未做）注册 `[project.scripts]` 入口——CLI 已可用 `python -m mcs.bench.multihop_rag`

## 7. 测试

- [x] 7.1 测试加载器 + corpus 子集/query 过滤（证据不可达的 query 被剔除）
- [x] 7.2 测试 Node→来源文档映射（含 merge 多来源取并集、去重）
- [x] 7.3 测试 Hit@k / MAP@k / MRR@k / recall@k（构造已知排名验证数值）
- [x] 7.4 测试 null_query 诊断与 question_type 分组
- [x] 7.5 测试运行器（mock build/query），验证增量落盘与 resume 跳过

## 8. 文档

- [x] 8.1 创建 `mcs/bench/MULTIHOP_RAG.md`（数据下载、build-once/query-many 用法、成本提示、指标口径）
- [x] 8.2 在该文档中标注与 hotpot bench 的架构差异（共享图 vs 每条独立）
