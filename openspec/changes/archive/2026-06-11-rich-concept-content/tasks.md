## 1. Prompt 重写

- [x] 1.1 重写 `mcs/prompts/extract_concepts.py` 的 SYSTEM_PROMPT，指导 LLM 生成 2-4 句自包含描述（含关键事实、关系、上下文），更新 USER_TEMPLATE 中 content 字段说明
- [x] 1.2 简化 `mcs/prompts/judge_relations.py` 的 SYSTEM_PROMPT 和 USER_TEMPLATE，移除 `initial_statements`、`statement`、`aliases_to_add` 字段说明，只保留 merge/create/no_op 三种动作；parse 函数保持宽容解析

## 2. 写入管线简化

- [x] 2.1 修改 `mcs/core/write_pipeline.py` 的 `_dispatch_merge`：移除 `initial_statements` → `extensions["statements"]["items"]` 写入；新增 concept content 追加到目标节点 content（子串去重）
- [x] 2.2 修改 `mcs/core/write_pipeline.py` 的 `_dispatch_create`：移除 `initial_statements` → `extensions["statements"]["items"]` 写入
- [x] 2.3 修改 `mcs/core/write_pipeline.py` 的 `_dispatch_attach`：变为 no-op（保留方法签名，打 deprecation warning 日志）
- [x] 2.4 修改 `mcs/core/write_pipeline.py` 的 `_sanitize_decisions`：`attach_statement` 不再要求 `target_id`

## 3. Rerank 简化

- [x] 3.1 修改 `mcs/plugins/postprocess/rerank.py` 的 `LexicalScorer.score`：移除 `extensions["statements"]["items"]` 读取，只从 `node.content` 提取词法 token

## 4. Deprecated 标记

- [x] 4.1 修改 `mcs/core/decisions.py`：在 `Decision` dataclass 的 `initial_statements`、`statement`、`aliases_to_add` 字段 docstring 标记 deprecated；在 `ConceptDraft.relation_hints` docstring 说明不再转为 statements

## 5. 测试更新

- [x] 5.1 更新 `tests/test_pipeline_write.py` 中 merge 相关测试：验证 content 追加行为（替代 statements 写入）
- [x] 5.2 更新 `tests/test_pipeline_write.py` 中 attach_statement 相关测试：验证变为 no-op
- [x] 5.3 运行 `pytest tests/ -x` 确认全部通过
