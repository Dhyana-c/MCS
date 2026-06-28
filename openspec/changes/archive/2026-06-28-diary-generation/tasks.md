## 1. 日记存储

- [ ] 1.1 `DiaryStore`（或复用 FragmentStore 模式，独立目录 `~/.mcs_memory/diaries/`）：`write(date, content)` 覆盖、`read(date) -> str | None`、`list_dates() -> list[str]` 倒排；目录自动创建
- [ ] 1.2 单测：写 / 覆盖 / 读不存在 None / 列表倒排 / 目录自动创建

## 2. 概括逻辑

- [ ] 2.1 概括 prompt：输入当天碎片（按时间序）→ 输出连贯第一人称日记叙述；强约束"仅基于碎片、不杜撰"
- [ ] 2.2 `DiaryGenerator.generate(date) -> str | None`：读当天碎片（FragmentStore）→ 空则返回 None → 否则 `llm_call` 概括 → 返回日记文本；超窗时分段摘要再合并
- [ ] 2.3 单测（fake LLM）：正常生成 / 空碎片返回 None / **不杜撰**（输出不含碎片外信息）/ **不遗漏约束在 prompt**（验证概括 prompt 含"覆盖每条碎片关键信息"——软保证，fake LLM 测不出真实遗漏，#11）/ 概括全部碎片含图谱噪声项（不与 Slice 2 去噪耦合，#3）/ 生成不触发 ingest（无建图副作用）

## 3. API（挂 mcs_agent app）

- [ ] 3.1 `POST /diary`（默认当天；无碎片 → `{ok:false, reason:"no_fragments"}`；否则生成 + 覆盖 + `{ok:true, date}`）；agent 无 `llm` → 503
- [ ] 3.2 `GET /diary/{date}`（读；不存在 404）
- [ ] 3.3 `GET /diaries`（列表倒排）
- [ ] 3.4 API 集成测试（TestClient）：生成 / 重生成覆盖 / 读 404 / 列表

## 4. 可选：定时（软依赖 Slice 2 调度器）

- [ ] 4.1 若 `ConsolidationScheduler` 存在，把"夜间生成当天日记"挂进夜间作业（条件集成，不写进 depends-on）
- [ ] 4.2 文档：日记是人读产物、不进图、可重生成；定时为可选

## 5. 文档

- [ ] 5.1 docs / README：个人记忆——日记生成一节（碎片 → 概括 → 日记，不进图）
