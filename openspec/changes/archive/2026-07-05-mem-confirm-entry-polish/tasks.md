## 1. C · note 后即时确认入口

- [x] 1.1 改 `mcs_mem/static/manage.html`「今日」视图 `render()`（[manage.html:470-486](../../../mcs_mem/static/manage.html)）：在 `#note-msg`（[line 473]）后新增专用受管容器 `<div id="note-confirm" class="msg"></div>`（design D4——**不**复用 `#note-msg`，其内容会被 `showMsg` 3s 定时清空 [manage.html:265]）。`submit` 成功分支除现有 `showMsg` + `loadToday()` + `updateInboxBadge()` 外，向 `#note-confirm` 填入「立即确认入图」链接式按钮，onclick 包装 `() => { confirmFragment(d.id); <清空 #note-confirm> }`（复用 `confirmFragment`，含 design D2 二次确认；清理见 1.2 / design D5）
- [x] 1.2 即时入口显式生命周期（design D4/D5）：① `submit` 开头清空 `#note-confirm`（覆盖"再记一条"）；② 点击确认后在 onclick 包装内清空 `#note-confirm`（覆盖"确认后残留"）——**注意 `loadToday()` 只重建 `#today-metrics`/`#today-frags`、不清 `#note-msg` 区，不能依赖它清理**，故必须显式清空

## 2. D · 确认二次确认防误（单点收口）

- [x] 2.1 改 `confirmFragment`（[manage.html:311](../../../mcs_mem/static/manage.html)）：函数入口加二次确认守卫 `if (!window.confirm('确认入图？该碎片将转为只读、不可撤销。')) return;`（design D2）——所有调用方（收件箱逐条 + 1.1 即时入口）一致获得防误。**仅**加二次确认守卫，**不**在此清理 `#note-confirm`（今日视图专属 DOM，清理属 1.2 调用侧，design D5）

## 3. 测试 + 验证

- [x] 3.1 `tests/test_manage_ui.py` 加结构断言：读取 `mcs_mem/static/manage.html` 文本，断言含 (a) 即时确认入口 hook——锁**稳定字面量**「立即确认入图」文案 + 容器 id `note-confirm`（**不**断言 `data-frag-id` 等运行时动态属性，design D4 说明）、(b) 二次确认标记 `window.confirm`——防回归误删
- [x] 3.2 回归：`.venv\Scripts\python.exe -m pytest tests/test_manage_ui.py tests/test_consolidate_api.py tests/test_fragments.py -q` 全绿
- [x] 3.3 手动验证：起服务（`.venv\Scripts\python.exe -m mcs_mem`）→ 今日视图记一条 → 反馈处出现「立即确认入图」→ 点击弹二次确认 → 确认后该条转 confirmed、出现在时间轴；收件箱点「确认」同样弹二次确认；不点即时入口时碎片留 pending
- [x] 3.4 503 降级（design D3）：无 memory 启动 → 点即时入口 → toast「确认不可用（无记忆）」

## 4. 文档同步

- [x] 4.1 核查 manage.html 内联 hint 文案（如「今日」视图「一条记录 = 一个 pending 碎片；确认后入图」）仍准确——无需改则不动（最小改动）
