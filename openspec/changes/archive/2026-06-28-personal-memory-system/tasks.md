## 1. 碎片存储模块（mcs_agent 内）

- [ ] 1.1 新增 `mcs_agent/fragments.py`：`FragmentStore` 类，构造时取碎片目录（默认 `~/.mcs_memory/fragments/`，`Path.home()` 兼容 Windows）
- [ ] 1.2 `append(content) -> (date, time)`：当天文件按 `HH:MM 内容` 追加，目录 / 文件不存在则自动建（`mkdir parents=True`）；同进程内追加串行化（文件锁或单 worker），**不碰 MCS**
- [ ] 1.3 `read(date) -> str | None`：读指定日期全文，不存在返回 `None`（不报错）
- [ ] 1.4 `overwrite(date, content)`：整文件覆盖（供 `PUT`），不存在则创建
- [ ] 1.5 `list_dates() -> list[str]`：列出已有 `YYYY-MM-DD.md`，按日期倒排
- [ ] 1.6 单测：首次建文件 / 追加不覆盖 / 多条顺序 / 空目录列表 / 读不存在返回 None / 覆盖 / 中文 + 特殊字符 / 目录自动创建 / 追加不触发 ingest

## 2. 捕获 API（挂 mcs_agent app）

- [ ] 2.1 在 `mcs_agent/app.py` 的 `create_app` 注入 / 构造 `FragmentStore`（app.state 持有），与 agent 解耦——无 `memory` 也能工作
- [ ] 2.2 `POST /note`：校验非空（空 / 纯空白 → 422），追加，返回 `{ok, date, time}`
- [ ] 2.3 `GET /fragments`：返回按日期倒排的文件名列表
- [ ] 2.4 `GET /fragments/{date}`：返回内容；不存在 → 404
- [ ] 2.5 `PUT /fragments/{date}`：整文件覆盖（自动建目录），返回 `{ok, date}`
- [ ] 2.6 `build_agent_from_env` / `run` 路径下确保 `FragmentStore` 也被构造（碎片目录可配，env 或默认）
- [ ] 2.7 API 集成测试（TestClient）：覆盖所有端点 + 空消息 422 + 读 404 + PUT 创建 + 与既有 `/chat` 同居一 app + fake agent（无 memory）下捕获仍可用

## 3. 配置与文档

- [ ] 3.1 碎片目录可配置（env `MCS_MEMORY_FRAGMENTS_DIR` 或既有配置入口），默认 `~/.mcs_memory/fragments/`
- [ ] 3.2 更新 `docs/` / README：记一节"个人记忆——捕获层"，说明随手记 → 碎片 MD（零 LLM），整合 / 日记 / UI 见后续 change
- [ ] 3.3 确认本片**不引入** apscheduler / ingest 依赖（地基片纯文件 IO）
