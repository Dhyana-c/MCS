## 1. 新增窄召回 prompt

- [x] 1.1 在 `mcs/prompts/select_facts.py` 新增 `WRITE_SYSTEM_PROMPT`（窄召回：选最相关、优先具体信息、可不选）
- [x] 1.2 新增 `WRITE_USER_TEMPLATE`（返回最相关编号列表，无相关返回 `[]`，按相关性降序）
- [x] 1.3 模块 docstring 补充：本文件同时承载读侧宽召回（`SYSTEM_PROMPT` / `USER_TEMPLATE`）与写侧窄召回（`WRITE_*`）两套口径

## 2. 注册 select_facts_write bundle

- [x] 2.1 `mcs/prompts/__init__.py` 在 `DEFAULT_PROMPTS` 注册 `select_facts_write`（system=WRITE_SYSTEM_PROMPT、template=WRITE_USER_TEMPLATE、parse=select_facts.parse）

## 3. 遍历参数化

- [x] 3.1 `QueryEngine._traverse` 新增形参 `select_purpose: str = "select_facts"`
- [x] 3.2 闭包 `_call_select` 内 `llm.call` 的 `purpose` 改用 `select_purpose`（去掉硬编码字面量）
- [x] 3.3 `query_nodes()` 调 `_traverse(seeds, processed_text, ctx, select_purpose="select_facts_write")`
- [x] 3.4 确认 `query()` 调用 `_traverse` 处不传该参数（读侧沿用默认）

## 4. 测试

- [x] 4.1 mock `LLMInterface.call` 捕获 `purpose`：`query()` 触发的事实筛选 MUST 为 `select_facts`
- [x] 4.2 mock 同上：`query_nodes()` 触发的事实筛选 MUST 为 `select_facts_write`
- [x] 4.3 断言 `DEFAULT_PROMPTS["select_facts_write"]` 存在，且其 `parse is select_facts.parse`
- [x] 4.4 窄召回 `parse` 边界：合法编号数组、空数组 `[]`、含 fence、非数组/非整数 → 行为与 `select_facts.parse` 一致（含 `LLMParseError`）
- [x] 4.5 覆盖正交：`prompt_overrides` 覆盖 `select_facts` 不影响 `select_facts_write`，反之亦然
- [x] 4.6 write_pipeline 阶段② 集成测试：`ctx.related` 经由 `select_facts_write` 路径产出，空结果不阻塞 ③
- [x] 4.7 回归：更新 `tests/test_skeleton.py` 的 DEFAULT_PROMPTS purpose 集合（加 `select_facts_write`）；新增默认 purpose 时该集合 MUST 同步

## 5. 文档与归档

- [x] 5.1 更新 `openspec/specs/query-pipeline/spec.md`（select_purpose 参数化）
- [x] 5.2 更新 `openspec/specs/lightweight-query/spec.md`（写侧窄召回 select_facts_write）
- [x] 5.3 确认 `docs/` 无需更新（仅 graph-model-design.md 提及 select_facts，与本变更无关）
- [x] 5.4 `openspec validate read-write-select-prompt-split --strict` 通过
