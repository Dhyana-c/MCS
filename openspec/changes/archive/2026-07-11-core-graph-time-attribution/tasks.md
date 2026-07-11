## 1. 挖 #2 根因 + 定位代码 ✅

- [x] 1.1 定位 `_dispatch_merge`（`mcs/core/write_pipeline.py:545-589`）：行 565-567 `node.content = f"{existing_content}\n{incoming}"` 非子串换行追加 —— 逐字落实 write-pipeline spec 行 138「追加」。**结论：非 bug，是 spec 规定的追加行为；本变更为 spec 行为变更（追加 → 语义合并）**。`_dispatch_merge` 调用点：行 349（⑤ 应用决策）+ 行 633（`_merge_concept_into` ⑤ 同名去重），均 write path。
- [x] 1.2 `extract_concepts` SYSTEM_PROMPT/USER_TEMPLATE 在 `mcs/prompts/extract_concepts.py` 行 22-49；时间污染源 = 行 27「关键的叶子属性（数值、**日期**、地点等）」明确鼓励日期进 content。
- [x] 1.3 查清拼 content 路径有 **3 条**（同款换行追加，DRY 违反）：`_dispatch_merge`（write）、`_try_read_repair`（`query_engine.py:386-392`，读路径）、`dedup_maintenance`（`dedup_maintenance.py:119-141`，后台删 dup）。第 4 条 `MemoryStore.merge_concepts`（`merge.py`）已用 LLM `merged_content`，正确不改。

## 2. extract_concepts prompt 守时间归属（#1）

- [x] 2.1 改 `mcs/prompts/extract_concepts.py` SYSTEM_PROMPT：**删除行 27「日期」鼓励**；概念 content **零时间**（禁任何时间词）；事实 content 禁相对/单次时间词、允许固定历史时间（1976）；带时间发生 → 去时间化作事实（时间归事件层）；不抽事件性命题（「X 的情况」、某次因果「X 导致 Y」）和偏好/模式（「喜欢 X」）
- [x] 2.2 USER_TEMPLATE 同步加时间归属约束 + 举例（"苹果公司"=概念零时间；"苹果创立于 1976"=事实带历史时间；"今天去按摩"=事件层 + 去时间化事实"用户去按摩"）

## 3. merge content 三路径统一（#2）+ 协调压缩段

- [x] 3.1 新增公共 helper `merge_content(target, incoming, merge_llm=None) -> str`（`mcs/core/content_merge.py`）：子串零成本（target ⊇ incoming 跳过、incoming ⊇ target 替换）；非子串 + merge_llm → LLM 语义合并；非子串 + None → 返回 target（不碰）
- [x] 3.2 新增 LLM 语义合并 purpose `merge_content`（去重 + 择优 + 守时间归属，返回单一稳定定义；与 `merge.py` content 合并措辞对齐）；**模板携带 `node_class` 按节点类型分流**——概念零时间、事实保留固定历史时间（否则同名事实合并会抹掉「1976 年」这类命题固有属性）
- [x] 3.3 `_dispatch_merge`（write path）改用 helper（传 merge_llm，携带目标节点 node_class）
- [x] 3.4 `dedup_maintenance`（当前未接入运行）改用 helper（**不传 merge_llm** → 子串才合删 dup、非子串保留 dup 不合）+ docstring 更新；保留重挂边 / 互斥禁合 / 超 T 挂起（彻底合并靠 write path）
- [x] 3.5 `_try_read_repair`（query path）改用 helper（**不传 merge_llm** → 非子串不碰）；保留"被并方节点不删"
- [x] 3.6 merge LLM 失败降级（保留 target content、warning——在 helper 内统一处理）
- [x] 3.7 merge 后 content 守时间归属（概念零时间、事实禁相对/单次时间保留固定历史——经 merge_content purpose 的 node_class 分流落实）
- [x] 3.8 协调 `merge-content-compaction`：压缩前提从「追加后」改「合并后」（压缩调用保留，改判断时点）

## 4. 测试

- [x] 4.1 `extract_concepts` prompt 时间归属防回归测试（`test_extract_concepts_prompt_enforces_time_attribution`：删「日期」鼓励 + 概念零时间 / 事实禁相对时间约束进 prompt 文本；LLM 行为级验证归 6.1 端到端）
- [x] 4.2 事件性命题 / 偏好不抽核心图——并入 4.1 的 prompt 文本防回归（行为级验证归 6.1）
- [x] 4.3 `merge_content` helper 测试：四象限 + LLM 失败/空返回降级（`tests/test_content_merge.py`）
- [x] 4.4 `_dispatch_merge` 测试：同名概念二次抽取 content 语义合并不拼接；**node_class 穿透**（概念/事实分别传入 merge_content purpose）
- [x] 4.5 `dedup_maintenance` 测试：子串才合删 dup、非子串保留 dup 不合不丢、互斥禁合仍生效
- [x] 4.6 `_try_read_repair` 测试：非子串 content 不碰（不拼）、子串才合、被并方节点保留、读路径零 LLM（`test_read_repair_non_substring_keeps_content_no_llm`）
- [x] 4.7 merge 后 content 超阈值仍触发 gen_summary 压缩 + 压缩失败降级（merge-content-compaction 协调）
- [ ] 4.8 全量回归（`.venv/Scripts/python.exe -m pytest -q`）——当前 1 个**与本变更无关**的遗留失败：`test_vendor_cytoscape_served_locally`（e598988 删 mcs_agent vendor 目录留下的死测试），其余全绿；该死测试清理后勾选

## 5. 清损坏数据（mcs_mem db）

- [ ] 5.1 抹掉/重抽 `mcs.db` 已损坏的概念/事实 content（按摩拼接、带时间词的节点）
- [ ] 5.2 确认清后图谱视图正常

## 6. 端到端验证

- [ ] 6.1 重启 mcs_mem + ingest 一条带时间日记 → 确认概念 content 零时间、事实无相对时间词、事件带时间
- [ ] 6.2 二次 ingest 同名概念 → 确认 content 语义合并不拼接
- [ ] 6.3 查询撞同名 → 确认 read-repair 不拼 content（非子串不碰）
