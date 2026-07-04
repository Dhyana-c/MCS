## 1. 碎片存储层重构（FragmentStore → JSONL 逐条 + 三态原语）

- [x] 1.1 `Fragment` 数据类（`id`/`date`/`time`/`content`/`status`/`event_id`/`created_at`，`status` ∈ pending/confirming/confirmed）+ JSON 序列化
- [x] 1.2 `parse_fragments` 从 `consolidation.py` **搬到 `fragments.py`**（碎片层职责，消除反向依赖）；`consolidation.py` 改 `from mcs_mem.fragments import parse_fragments`
- [x] 1.3 `create(content)`：生成唯一 `id`（`{date}T{HH:MM:SS}`，同秒冲突 `-N`）、建 `pending` 碎片追加当天 JSONL，返回 `(id, date, time)`
- [x] 1.4 `read_all(date)`：返回当天全部碎片（各态，按 `time` 排序）
- [x] 1.5 `get(id)` / `find(date, id)`
- [x] 1.6 `update(id, content)`：改 content，**仅 pending**（confirming/confirmed 抛状态错）
- [x] 1.7 `delete(id)`：删碎片，**仅 pending**
- [x] 1.8 三态原语（纯文件、内锁原子）：`begin_confirm(id)` CAS `pending→confirming`（非 pending 失败）、`confirm_mark(id, event_id)` `confirming→confirmed`、`abort_confirm(id)` `confirming→pending`
- [x] 1.9 移除旧 `append`(MD 行) / `read`(全文) / `overwrite` / `mtime` / `VersionMismatch`
- [x] 1.10 `__init__` MD→JSONL 幂等迁移：`parse_fragments` 解析 → pending 碎片写 JSONL，`.md`→`.md.migrated` 备份
- [x] 1.11 `__init__` 启动清理：扫残留 `confirming` → 回退 `pending`（防崩溃悬空）

## 2. 整合层重写（Consolidator）

- [x] 2.1 删除 `Denoiser` / `LLMDenoiser` / `_DefaultDenoiser` + 删除 `mcs_mem/prompts/denoise.py`
- [x] 2.2 `Consolidator.confirm_one(id)`：`begin_confirm`(CAS) → `ingest_structured` → `confirm_mark`；`ingest` 失败 `abort_confirm` 回退 pending；已 confirming/confirmed 幂等返回 already
- [x] 2.3 `Consolidator.consolidate(date)`：读当天 pending → 循环 `confirm_one` → 返回 `{confirmed, skipped, failed, date}`
- [x] 2.4 `ConsolidationTracker` 降级：移除单日 `done`/`running` 锁定拒重入；记录 `{date, last_run, confirmed, failed}`；保留 `_mutex` 互斥

## 3. API 路由改造（mcs_mem/app.py）

- [x] 3.1 `POST /note`：创建 pending 碎片，响应 `{ok, id, date, time}`
- [x] 3.2 `GET /fragments/{date}`：返回 `{date, fragments:[{id,time,content,status,event_id}]}`
- [x] 3.3 `POST /fragments/{id}/confirm`：调 `confirm_one(id)` → `{ok, id, status, event_id}`；无 memory 503；id 不存在 404
- [x] 3.4 `PUT /fragments/{id}`：改 content，仅 pending；confirming/confirmed → 409；不存在 → 404
- [x] 3.5 `DELETE /fragments/{id}`：删碎片，仅 pending；confirming/confirmed → 409
- [x] 3.6 `POST /consolidate`：确认指定日期剩余 pending，响应 `{ok, date, confirmed, skipped, failed}`
- [x] 3.7 `GET /consolidate/status(es)`：返回观测记录
- [x] 3.8 移除旧 `PUT /fragments/{date}` 整文件覆盖 + `mtime`/`expected_mtime` 契约（含旧 pydantic model）
- [x] 3.9 **移除 today warning 逻辑**（现有 `if target == date.today(): warning=...`）

## 4. scheduler 对齐（mcs_mem/scheduler.py）

- [x] 4.1 `_run_yesterday` 日志字段改 `confirmed`/`skipped`/`failed`
- [x] 4.2 验证 cron / env / lifespan 不变

## 5. 日记适配（mcs_mem/diary.py）

- [x] 5.1 `DiaryGenerator` 改用 `fragment_store.read_all(date)` 拼 `HH:MM 内容` 文本（替代 `read` MD 全文）
- [x] 5.2 `_FragmentStoreProto` 加 `read_all` 方法签名
- [x] 5.3 验证超窗分块（`_summarize_long`）与 `{date}` 注入不变

## 6. 前端改造（mcs_mem/static/manage.html，无批量按钮）

- [x] 6.1 碎片块：按日期分组（倒排）展示；`GET /fragments` + 每组 `GET /fragments/{date}` 载入两态列表
- [x] 6.2 pending 条目：内联 [确认][编辑][删除]；confirming/confirmed 条目只读 + ✓ + event_id
- [x] 6.3 逐条确认 / 编辑 / 删除交互（`/fragments/{id}/confirm`、`PUT`、`DELETE`）
- [x] 6.4 整合块：纯日历展示（每日 pending/confirmed 计数），**无批量按钮**
- [x] 6.5 日记块：侧栏按天列表强化（`GET /diaries` 倒排、点击载入）

## 7. 迁移与启动验证

- [x] 7.1 demo 数据 `mcs_mem_demo_data/fragments/*.md`（若有）经迁移转 JSONL、`.md.migrated` 备份；或清空用新数据复测
- [x] 7.2 `_run_mem_demo.py` 启动验证：脚本无需改动（经 `create_app` 自动迁移）；捕获 / 确认入图 / 整合 / 日记 / scheduler 全链路由 TestClient 集成测试覆盖（含 fake LLM）。**未跑真实 deepseek 起服务**（无 API key），需用户用真实 key 复跑做最终验收
- [x] 7.3 行为验证：分天两态 / 确认即入图 / confirmed 只读 / scheduler 兜底均由自动化测试覆盖（test_capture_api / test_consolidate_api / test_manage_ui）。**浏览器手动点击未做**，留用户做最终 UI 验收

## 8. 测试（含边界）

- [x] 8.1 `test_capture_api`：CRUD + 三态原语 + 状态门控（confirming/confirmed 不可改删 409）+ 同秒多条 id 唯一 + note 空 422
- [x] 8.2 `test_consolidation`：`confirm_one` 协调（begin→ingest→mark，失败 abort 回退）、批量确认、空 pending 返回 skipped、重试仅处理 pending（confirmed 跳过幂等）；移除去噪测试
- [x] 8.3 **并发 CAS 测试**：并发确认同一条仅一个 `ingest`、抢占失败者不重复入图
- [x] 8.4 `test_diary`：日记基于 `read_all` 结构化碎片（各态全量）
- [x] 8.5 `test_manage_ui`：碎片分天两态可达、确认交互、整合块无批量按钮
- [x] 8.6 MD→JSONL 迁移测试：幂等（已有 jsonl 跳过）、`.md.migrated` 备份、解析正确
- [x] 8.7 启动清理测试：残留 `confirming` → 回退 pending
- [x] 8.8 全量回归：`.venv\Scripts\python.exe -m pytest -q` 通过
