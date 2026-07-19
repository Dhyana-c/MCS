## Phase 1: Oracle 版评测框架

### T1: 数据拉取与预处理
- 实现 `bench/longmemeval/scripts/download_data.py`
  - 从 HuggingFace 下载 oracle / S 版数据（wget）
  - 校验文件大小 / MD5
  - 输出到 `bench/longmemeval/data/`
- 实现 `bench/longmemeval/data.py`
  - `LongMemEvalQuestion`: 问题数据类（question_id, question_type, question, answer, question_date, haystack_dates, haystack_sessions, answer_session_ids）
  - `LongMemEvalDataLoader`: 加载 oracle / S 版 JSON
  - 时间戳解析：`"2023/04/10 (Mon) 17:50"` → `datetime`
  - 会话排序：按 haystack_dates 升序
  - 按类型过滤：`filter_by_type(question_type)` + abstention 子集识别（`_abs` 后缀）
  - 预处理缓存：解析后序列化到 `data/preprocessed/`，加速后续加载

### T2: 对话式 ingest 建图
- 实现 `bench/longmemeval/builder.py`
  - `build_question_graph(question: LongMemEvalQuestion, llm, db_dir)`: 按会话顺序 ingest
  - 会话→文本拼接（`[时间] role: content` 格式，user/assistant 角色标注）
  - `IngestInput(content=拼接文本, timestamp=会话时间.isoformat(), metadata={"doc_id": question_id, "chunk_id": haystack_session_id})`——字段名 `timestamp` 非 `now`（ISO 字符串）；`metadata` 供 source_tracking 记 session 级溯源（检索轨用）
  - 每题独立 db（`longmemeval_{question_id}.db`），全部 `__reality__` universe（temporal 路线若定为 work_id 化则此处改，见 design Open Questions）
  - resume：跳过已存在的 db 文件
- 框架 ingest 建图（不修改 `bench/agent_build.py` 共享模块）

### T3: 评测指标
- 实现 `bench/longmemeval/metrics.py`
  - **主指标 = LLM-judge 正确率**（对齐 LoCoMo bench / Zep / LongMemEval 官方口径），F1 副指标单列
  - judge 按类型定制（见 D4）：
    - temporal-reasoning: judge 语义等价；副 F1 + 时间偏移容忍（不进主表）
    - multi-session: judge 语义等价（32 个 int 计数题判数值相等）
    - knowledge-update: judge 只认最新值（旧值=错）
    - single-session-*: judge 语义等价
    - single-session-preference: judge 按 rubric 评分
    - abstention: judge 弃答判定（不用关键词匹配）
  - 检索评测：Recall@k（answer_session_ids ↔ source_tracking 的 chunk_id，session 级；k=5,10,20；any/all-evidence hit）
  - 聚合报告：按类型 + 整体

### T4: Agent 评测脚本
- 实现 `bench/longmemeval/scripts/agent_eval.py`
  - 加载问题 → 逐题建图 → agent 评测 → 写结果 JSONL
  - agent prompt 适配（用户-助手对话记忆场景）
  - knowledge-update 特殊处理（验证最新值）
  - abstention 特殊处理（弃答 = 正确）
  - preference 类 rubric 评分
  - resume：跳过已评测 question_id
- 实现 `bench/longmemeval/scripts/analyze.py`
  - 汇总结果 → 生成 REPORT.md
  - 与 Mem0/Zep 基线对比表

### T5: 配置 + 文档
- `bench/longmemeval/config/default.json`
- `bench/longmemeval/README.md`：使用说明 + 数据下载 + 成本预估
- `bench/longmemeval/data/README.md`：数据获取说明（数据不入 git，.gitignore）

## Phase 2: S 版扩展（后续）

### T6: S 版评测
- 下载 S 版数据（277MB）
- 每题 ingest 含填充会话（~115K token/题）
- 对比 Oracle vs S 版结果，量化"大海捞针"能力衰减

## 依赖关系

```
T1 → T2 → T3 → T4 → T5
T6 依赖 T1-T5 跑通
```

## 预估成本（Oracle 版）

| 阶段 | LLM 调用 | 预估 token | 说明 |
|------|---------|-----------|------|
| Ingest（500 题 × avg 1.9 会话） | ~950 次 | ~5.7M | 每会话一次 ingest × ~6K token |
| Agent QA（500 题） | ~5000 次 | ~11M | 每题 ~22K token（agent 多轮工具循环） |
| LLM judge（500 题） | ~500 次 | ~1.25M | 每题 ~2.5K token |
| **合计** | | **~18M** | Oracle 版可控 |

## 预估成本（S 版 Phase 2）

| 阶段 | 预估 token | 说明 |
|------|-----------|------|
| Ingest（500 题 × ~48 会话） | ~144M | 每题 ~48 会话 × ~6K token/次 |
| Agent QA + judge | ~12M | 同 Oracle |
| **合计** | **~156M** | 成本较高，需确认后执行 |
