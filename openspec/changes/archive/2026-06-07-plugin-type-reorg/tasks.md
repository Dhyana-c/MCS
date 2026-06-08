## 1. 插件目录结构重组

- [x] 1.1 创建新类型目录：`mcs/plugins/{entry,trim,postprocess,preprocess,maintenance,index,llm,seed_selector}/`
- [x] 1.2 移动 ENTRY 类型插件：`alias_entry.py`、`hub_fallback.py` → `plugins/entry/`
- [x] 1.3 移动 TRIM 类型插件：`priority_trim.py` → `plugins/trim/`
- [x] 1.4 移动 POSTPROCESS 类型插件：`rerank.py`、`summary.py` → `plugins/postprocess/`
- [x] 1.5 移动 PREPROCESS 类型插件：`idempotency_check.py`、`source_tracking.py`、`cross_doc_linker.py` → `plugins/preprocess/`
- [x] 1.6 移动 MAINTENANCE 类型插件：`fanout_reducer.py`、`summary_regen.py`、`community_merger.py` → `plugins/maintenance/`
- [x] 1.7 移动 INDEX 类型插件：`alias_index.py` → `plugins/index/`
- [x] 1.8 移动 LLM 类型插件：`deepseek_llm.py`、`claude_llm.py`、`ollama_llm.py` → `plugins/llm/`
- [x] 1.9 移动 SEED_SELECTOR 类型插件：`llm_seed_selector.py` → `plugins/seed_selector/`
- [x] 1.10 为每个新目录创建 `__init__.py` 并导出插件类
- [x] 1.11 删除 `mcs/plugins/phase1/` 和 `mcs/plugins/phase2/` 目录（含 `__pycache__`）

## 2. 更新插件注册表与引用路径

- [x] 2.1 更新 `mcs/presets/phase1.py` 中所有插件 import 路径
- [x] 2.2 更新 `mcs/core/write_pipeline.py` 中的 `from mcs.plugins.phase1.fanout_reducer` import
- [x] 2.3 更新 `mcs/plugins/entry/hub_fallback.py` 内部对 `fanout_reducer` 的 import
- [x] 2.4 更新 `mcs/plugins/preprocess/cross_doc_linker.py` 内部 import
- [x] 2.5 更新 `bench/multihop-rag/scripts/` 下脚本对 `doc_rerank` 的 import（bench 迁移后）
- [x] 2.6 更新 `scripts/cross_doc_link_pass.py` 的 import

## 3. 更新测试文件 import 路径

- [x] 3.1 更新 `tests/test_skeleton.py` 中所有 phase1 import
- [x] 3.2 更新 `tests/test_fanout_reducer.py` import
- [x] 3.3 更新 `tests/test_hub_fallback.py` import
- [x] 3.4 更新 `tests/test_rerank.py` import
- [x] 3.5 更新 `tests/test_directed_hierarchy.py` import
- [x] 3.6 更新 `tests/test_directed_navigation.py` import
- [x] 3.7 更新 `tests/test_seed_graph.py` import
- [x] 3.8 更新 `tests/test_persistence.py` import
- [x] 3.9 更新 `tests/test_pipeline_write.py` import
- [x] 3.10 更新 `tests/test_anti_regression.py` import
- [x] 3.11 更新 `tests/test_bench_doc_rerank.py` import
- [x] 3.12 更新 `tests/test_community_merger.py` import
- [x] 3.13 更新 `tests/test_cross_doc_linker.py` import
- [x] 3.14 更新 LLM 测试文件 import（`test_claude_llm.py`、`test_deepseek_llm.py`、`test_ollama_llm.py`）

## 4. bench 目录迁移与重构

- [x] 4.1 创建 `bench/plugins/` 目录及 `__init__.py`
- [x] 4.2 迁移 `mcs/bench/doc_rerank.py` → `bench/plugins/doc_rerank.py`
- [x] 4.3 更新 `bench/plugins/doc_rerank.py` 对 `rerank._tokenize` 的 import 路径
- [x] 4.4 创建 `bench/multihop_rag/` 目录结构
- [x] 4.5 拆分 `multihop_rag.py` 数据加载代码 → `bench/multihop_rag/data.py`
- [x] 4.6 拆分 `multihop_rag.py` 图构建代码 → `bench/multihop_rag/builder.py`
- [x] 4.7 拆分 `multihop_rag.py` 指标计算代码 → `bench/multihop_rag/metrics.py`
- [x] 4.8 拆分 `multihop_rag.py` 评测运行器 → `bench/multihop_rag/runner.py`
- [x] 4.9 创建 `bench/multihop_rag/__init__.py` 导出公共接口
- [x] 4.10 更新 `bench/multihop-rag/scripts/` 下脚本 import
- [x] 4.11 删除 `mcs/bench/` 目录（含 `__init__.py`、`README.md`、`hotpot.py`、`MULTIHOP_RAG.md` 等）
- [x] 4.12 迁移 `mcs/bench/hotpot.py` → `bench/hotpotqa/runner.py`（或合并到现有结构）

## 5. 验证与清理

- [x] 5.1 运行全量测试：`.venv/Scripts/python.exe -m pytest -q` 确保全部通过
- [x] 5.2 检查无 `from mcs.plugins.phase1` 残留引用
- [x] 5.3 检查无 `from mcs.bench` 残留引用
- [x] 5.4 检查 `mcs/plugins/` 下无 `phase1`/`phase2` 残留目录
- [x] 5.5 更新 `CLAUDE.md` 相关文档（如有必要）
- [x] 5.6 更新 `openspec/specs/bench-directory-structure/spec.md` 反映新结构