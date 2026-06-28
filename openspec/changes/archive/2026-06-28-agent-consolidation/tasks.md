## 1. 结构化 ingest 原语（改 MemoryStore）

- [ ] 1.1 `MemoryStore.ingest_structured(content, timestamp) -> event_id`：worker 线程内 `mcs.ingest(IngestInput(content, timestamp))`、返回 `wctx.event_node.id`
- [ ] 1.2 单测：timestamp 落 `event_meta.timestamp`（非 now）/ 返回事件 id / 经单 worker / `learn` 契约不变

## 2. 解析

- [ ] 2.1 `parse_fragments(md_text, date) -> list[(iso_ts, content)]`：行 `HH:MM 内容` → `(date+HH:MM ISO, 正文)`；无法解析跳过 + WARNING；不调 LLM
- [ ] 2.2 单测：正常多行 / 跳过格式错误行 / 空内容 / 中文 + 特殊字符 / content 不含时间前缀

## 3. 去噪（Consolidator 应用层前置过滤）

- [ ] 3.1 在 `Consolidator` 内实现去噪：逐碎片调 LLM 判「值得记 / 噪声」，**仅保留的送 `ingest`**——**不**做成 `WRITE_PREPROCESS` 插件（其契约纯变换、MUST NOT skip，丢不掉输入；见 plugin-protocol spec）
- [ ] 3.2 去噪 prompt：逐碎片判去留，保守（拿不准就留）；**只判去留，不合成、不归并、不抽概念**
- [ ] 3.3 LLM 去噪判定在 worker 线程**外**执行（Consolidator 应用层；不阻塞 MCS 单 worker）；去噪只作用整合路径，不碰 agent 直接 learn
- [ ] 3.4 单测（fake LLM）：噪声被丢（不进 ingest）/ 多条同事不被合成（各自保留）/ 拿不准保留 / agent 直接 learn 不经去噪

## 4. 整合主流程

- [ ] 4.1 `ConsolidationStatus`（date/status/events/consolidated_at）+ `ConsolidationTracker`（本地 JSON `~/.mcs_memory/consolidation_status.json`、重启恢复）
- [ ] 4.2 单日锁定：`done` → `already`，无 force
- [ ] 4.3 整合互斥锁（应用级，运行中再触发 → `running`）
- [ ] 4.4 `Consolidator.consolidate(date)`：读 MD（FragmentStore）→ 解析 → 去噪 → **逐条** `ingest_structured` 收集事件 id → tracker 置 `done` + 事件数；单条失败续跑；失败置 `failed`
- [ ] 4.5 单测：空碎片不入图 / 事件数 = 保留碎片数（不合成）/ 事件时间 = 碎片时间无塌缩 / 单日锁定拒重整 / 单条失败容错续跑 / 互斥 running

## 5. 调度器

- [ ] 5.1 `apscheduler` 加进 `pyproject.toml`
- [ ] 5.2 `ConsolidationScheduler`（封装 `BackgroundScheduler`）：默认 cron `30 0 * * *`、**目标日期=昨天**，可配 / 可禁用
- [ ] 5.3 与 `mcs_agent` app 的 FastAPI lifespan 集成（起 / 关）
- [ ] 5.4 整合完成 INFO 日志 / 失败 ERROR + 状态 `failed`
- [ ] 5.5 单测：注册 / 触发整合昨天 / 禁用 / 生命周期

## 6. API（挂 mcs_agent app）

- [ ] 6.1 `POST /consolidate`（无 force；**无 date 默认昨天**；整合今天须显式 date + 响应带 `warning`；已整合 → `already`）；agent 无 memory/llm → 503
- [ ] 6.2 `GET /consolidate/status?date=...`（单日）
- [ ] 6.3 `GET /consolidate/statuses`（全量，供 Slice 4 日历）
- [ ] 6.4 API 集成测试（TestClient）：触发 / 单日锁定 / running / 单日 + 全量状态 / 无 memory 503

## 7. 端到端 + 文档

- [ ] 7.1 端到端：记录多条不同时间消息（Slice 1）→ 整合 → 一碎片一事件按碎片时间入图 + 去噪生效（噪声不入图）→ recall 可召回
- [ ] 7.2 文档：整合管线说明 + "done 后改 MD 不重整"取舍 + "今天别手动整合（留给明早整合昨天，否则今天后续消息成孤儿）"提示
