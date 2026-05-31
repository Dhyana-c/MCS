## 1. 模块结构

- [x] 1.1 创建 `mcs/bench/__init__.py` 模块入口
- [x] 1.2 创建 `mcs/bench/hotpot.py` HotpotQA 评测核心代码
- [x] 1.3 在评测依赖中加入 `ujson`（`hotpot_evaluate_v1.py` 顶部 `import ujson`，否则 import 失败）

## 2. 数据加载

- [x] 2.1 实现 `HotpotItem` dataclass（_id, question, answer, supporting_facts, context, type, level）
- [x] 2.2 实现 `HotpotDataLoader` 类，支持加载 JSON 和分层采样
- [x] 2.3 实现 type 分层采样逻辑（dev 全为 hard，不分 level）；支持 `uniform`/`proportional` 两种策略

## 3. Ingest 适配

- [x] 3.1 实现 context 段落格式化：`[title, sentences]` → `"{title}: {s1}. {s2}."`
- [x] 3.2 实现 `ingest_hotpot_item()`：为每条数据创建独立 MCS 实例（独立 `:memory:`/db，避免 load-on-startup 污染），摄入时传 `doc_id=_id`/`chunk_id=<段落序号>`/`section_title=<段落标题>` 元数据

## 4. Query 适配

- [x] 4.1 实现 answer 提取：从 `List[Node]` 中提取 yes/no 或实体答案
- [x] 4.2 实现 supporting_facts 提取：从 `node.extensions["source_tracking"]["sources"]` 的 `section_title` 取 title，sent_idx 取 0，title 去重
- [x] 4.3 实现 `extract_prediction()` 整合 answer + supporting_facts 提取

## 5. 评测运行器

- [x] 5.1 实现 `HotpotEvalConfig` dataclass
- [x] 5.2 实现 `HotpotEvalRunner` 类
- [x] 5.3 实现 `run()` 方法：加载 → 逐条 ingest+query → 收集预测
- [x] 5.4 写出预测文件 `{"answer": {...}, "sp": {...}}`，并导出只含本次 `_id` 的子集 gold 文件
- [x] 5.4b 复用 `hotpot_evaluate_v1.update_answer`/`update_sp` 自行聚合得指标字典（不依赖只 `print` 的 `eval()`）
- [x] 5.5 实现进度显示和预测结果输出
- [x] 5.6 实现断点续跑：保存/加载已完成的 `_id` 列表
- [x] 5.7 实现 dry-run 模式：仅统计预估 token

## 6. CLI 入口

- [x] 6.1 实现 `mcs.bench.hotpot:main()` CLI 入口
- [x] 6.2 支持 `--subset`, `--llm`, `--output`, `--dry-run`, `--no-resume` 参数
- [x] 6.3 在 `pyproject.toml` 中注册 `[project.scripts]` 入口（可选）

## 7. 测试

- [x] 7.1 测试 HotpotDataLoader 分层采样
- [x] 7.2 测试 context 格式化和 ingest
- [x] 7.3 测试 answer 和 supporting_facts 提取
- [x] 7.4 测试评测运行器（使用 mock LLM）

## 8. 文档

- [x] 8.1 更新 README.md 添加评测使用说明
- [x] 8.2 创建 `mcs/bench/README.md` 说明评测框架用法
