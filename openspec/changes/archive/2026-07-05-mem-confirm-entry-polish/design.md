## Context

管理看板（`mcs_mem/static/manage.html`）当前 note → 入图路径不顺：

- 「今日」视图 `submit` handler（[manage.html:478-486](../../../mcs_mem/static/manage.html)）：note 成功 → `showMsg('✓ 已记录 ' + d.time, 'ok')` + `loadToday()` + `updateInboxBadge()`，**无即时确认路径**——要入图得去收件箱找刚记的那条点「确认」（2 跳）。
- `confirmFragment(id)`（[manage.html:311](../../../mcs_mem/static/manage.html)）：直接调 `/confirm`，**无防误**；503 → toast「确认不可用」。
- `renderFragment` pending 分支（[manage.html:278](../../../mcs_mem/static/manage.html)）：「确认」按钮 onclick 直接 `confirmFragment`。

`POST /note` 契约返回 `{ok, id, date, time}`（[app.py:194](../../../mcs_mem/app.py)），`id` 即新碎片 id——前端已握有做即时确认所需的一切。本次仅打磨这条路径的顺滑度与安全性：不动后端、不动三态、不碰 spec 的批量确认禁令。

## Goals / Non-Goals

**Goals:**
- note 成功反馈提供**即时单条确认**入口（2 跳 → 1 跳，可忽略）。
- 所有确认入口加**二次确认**防误（`confirmed` 不可撤销）。

**Non-Goals:**
- 不加任何批量确认 / 整合操作入口（保留 spec「整合块 SHALL NOT 批量」，[memory-management-ui spec:44](../../specs/memory-management-ui/spec.md)）。
- 不改后端 / 三态状态机 / scheduler / MCS 核心。
- 不引入前端测试框架 / 浏览器自动化。

## Decisions

**D1 · 即时确认入口 = 记录反馈处的链接式按钮（复用 `confirmFragment`）**

note 成功后，在 `#note-msg` 反馈处渲染一个指向 `d.id` 的「立即确认入图」按钮，onclick 复用既有 `confirmFragment(d.id)`——零新逻辑分支。
- 备选 A：note 后**自动 confirm**（不弹入口、直接入图）——**否决**：违背"碎片是 pending 去噪缓冲"设计（用户应能在 ingest 前审视删改），且与"图谱保守"定位冲突。
- 备选 B：跳转收件箱并定位该条——**否决**：仍是 2 跳，没解决顺滑度。

**D2 · 二次确认用原生 `window.confirm()`（单点收口在 `confirmFragment`）**

在 `confirmFragment` 内部、调 `/confirm` 前加 `if (!confirm('确认入图？该碎片将转为只读、不可撤销')) return;`。所有调用方（逐条「确认」+ D1 即时入口）自动获得防误——单点改动、零新状态机。
- 备选：inline 二次确认控件（更美观）——**否决**：增加 DOM/状态复杂度，收益不抵成本（最小改动原则；项目"纯 HTML/JS 无构建"调性）。

**D3 · 无 consolidator 时即时入口仍渲染、点后 503 优雅降级**

`/note` 不依赖 memory（纯文件旁路），但 `/confirm` 依赖（无 memory 时 503）。最小改动：**不在加载时探测** consolidator，即时入口始终渲染，点击后若 503 走现有 `confirmFragment` 的 503 分支 toast「确认不可用（无记忆）」。
- 备选：加载时调 `/consolidate/statuses` 探测、不可用则不渲染入口——**否决**：多一个请求 + 状态耦合，违背最小改动；现有 503 处理已足够。

**D4 · 即时入口用专用受管容器 `#note-confirm`（非 `#note-msg` 子节点、非无主兄弟）**

`showMsg` 以 `textContent=` + 3s 定时清空 `#note-msg`（[manage.html:265](../../../mcs_mem/static/manage.html)）——按钮塞进去 3 秒即被吞；而 `loadToday()` 只重建 `#today-metrics`/`#today-frags`、**不触碰 `#note-msg` 区**（[manage.html:360-378](../../../mcs_mem/static/manage.html)），故无主兄弟节点会在"确认后 / 再记一条后"残留、指向旧 id。解法：专用容器 `#note-confirm`（`#note-msg` 兄弟），生命周期显式管理——每次 `submit` 开头清空 → note 成功填入指向 `d.id` 的链接式按钮 → 点击确认后清空。
- 备选：复用 `#note-msg` 承载按钮——**否决**：3s 被 showMsg 定时吞掉。
- 备选：无主兄弟节点、依赖 `loadToday` 清理——**否决**：`loadToday` 不重建 `#note-msg` 区，清不掉，会残留旧 id。

**D5 · 即时入口的容器清理落在按钮 onclick 包装、不落 `confirmFragment`**

`confirmFragment` 为收件箱逐条 + 即时入口**共用单点**（[manage.html:311](../../../mcs_mem/static/manage.html)），成功分支 `refreshFrags()→loadToday()` 只刷碎片列表、**不清 `#note-confirm`**（也不该耦合今日视图 DOM）。故 D2 二次确认守卫放 `confirmFragment` 内（单点防误，正确），但即时入口清理须在其 handler 包装：`() => { confirmFragment(d.id); <清空 #note-confirm> }`。503 失败时容器一并清空（用户得 toast、可去收件箱重试；符合最小改动）。

> **取舍说明（取消即清空）**：onclick 包装**不 await** `confirmFragment`、也不读其 `confirm` 结果，故用户在二次确认弹窗点「取消」时 `#note-confirm` 同样被清空、「立即确认入图」入口消失。此时碎片仍 `pending`、可去收件箱逐条确认或等 scheduler 兜底，UX 损失可接受。要"仅 confirm 通过才清空"需让 `confirmFragment` 回传 bool、或把今日视图 DOM 清理耦合进 `confirmFragment` 成功分支——二者皆违背本节"单点收口、不耦合今日 DOM"原则，故按最小改动维持现状。

## Risks / Trade-offs

- **[原生 `confirm()` 体验一般 / 极少数浏览器策略限制]** → 可接受：项目定位为本地个人工具，非公网 SaaS；后续要美化改 inline 即可，单点改动。
- **[即时入口让用户更易"记完即确认"、弱化去噪审视]** → 入口**可忽略**且**仍过二次确认**；不改变 pending 缓冲语义，只缩短"已审视后确认"的路径。可接受。
- **[前端 JS 交互无 pytest 覆盖]** → 结构断言（即时入口 hook + 二次确认调用点存在）防回归误删；端到端靠手动验证（在 tasks 注明）。断言锁**稳定字面量**：「立即确认入图」文案 + `window.confirm`，**不**断言运行时动态属性（如 `data-frag-id`，`renderFragment` 走 `createElement`、源码未必含该字面量）。

## Migration Plan

纯前端单文件改动（`manage.html`），无数据 / 契约迁移。回滚 = `git revert` 该文件。

## Open Questions

（无——scope 已与用户确认收敛为 C + D。）
