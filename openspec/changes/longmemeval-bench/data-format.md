# longmemeval-bench spec

## 数据格式

### LongMemEval Oracle / S / M 版

三个版本共享相同的 500 个问题（question_id 完全一致），区别仅在 haystack 规模。

```json
[
  {
    "question_id": "gpt4_2655b836",
    "question_type": "temporal-reasoning",
    "question": "What was the first issue I had with my new car after its first service?",
    "answer": "GPS system not functioning correctly",
    "question_date": "2023/04/10 (Mon) 23:07",
    "haystack_dates": ["2023/04/10 (Mon) 17:50", "2023/04/10 (Mon) 18:30"],
    "haystack_session_ids": ["answer_4be1b6b4_2", "answer_4be1b6b4_3"],
    "haystack_sessions": [
      [
        {"role": "user", "content": "I just bought a new Toyota Camry last week!"},
        {"role": "assistant", "content": "Congratulations! How are you liking it?"}
      ],
      [
        {"role": "user", "content": "After the first service, the GPS stopped working..."}
      ]
    ],
    "answer_session_ids": ["answer_4be1b6b4_2", "answer_4be1b6b4_3"]
  }
]
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| question_id | str | 唯一标识；以 `_abs` 结尾 = abstention 题 |
| question_type | str | 6 种之一（见下表） |
| question | str | 问题文本 |
| answer | str 或 int | 短语答案（468 str / 32 int）或 rubric（preference 类，avg 390 字符） |
| question_date | str | 问题日期，格式 `"2023/04/10 (Mon) 23:07"` |
| haystack_dates | list[str] | 各历史会话的时间戳 |
| haystack_session_ids | list[str] | 各历史会话的 ID |
| haystack_sessions | list[list[dict]] | 各会话的 turn 列表 |
| answer_session_ids | list[str] | 包含答案证据的会话 ID（1-6 个，avg 1.9） |

### Oracle vs S 版差异

| 版本 | 每题会话数 | 每题 token | 文件大小 |
|------|-----------|-----------|---------|
| Oracle | 1-6（仅证据会话） | ~6.6K avg | 15MB |
| S | ~48（证据 + 填充） | ~115K | 277MB |
| M | ~500 | ~1.5M | 1.69GB |

Oracle 版的 haystack_session_ids = answer_session_ids（子集关系：answer ⊂ haystack）。
S/M 版的 haystack_session_ids ⊃ answer_session_ids，多出的是填充会话。

### 问题类型分布

| question_type | 数量 | 答案特征 | 评测指标（主 = LLM-judge；F1 副指标单列） |
|--------------|------|---------|---------|
| temporal-reasoning | 133 | 短语（avg 44 字符），含时间线索 | judge 语义等价；副 F1 + 时间容忍 |
| multi-session | 133 | 短语/整数（avg 25 字符，32 个 int） | judge 语义等价（int 判数值相等） |
| knowledge-update | 78 | 短语（avg 20 字符），只看最新值 | judge 只认最新值（旧值=错） |
| single-session-user | 70 | 短语（avg 20 字符） | judge 语义等价 |
| single-session-assistant | 56 | 短语（avg 38 字符） | judge 语义等价 |
| single-session-preference | 30 | rubric（avg 391 字符） | judge 按 rubric 评分 |
| abstention (_abs) | 30 | N/A（弃答=正确） | judge 弃答判定 |

注（实测）：abstention 30 题以 `_abs` 后缀标识，**分布于类型内**而非独立类型（6 类合计 500）：multi-session 12、temporal-reasoning 6、knowledge-update 6、single-session-user 6。时间戳格式全量 0 解析失败；int 答案 32 个（均 multi-session）。

## 数据拉取流程

### 下载脚本

```bash
# bench/longmemeval/scripts/download_data.py

DATA_DIR="bench/longmemeval/data"
HF_BASE="https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main"

# Oracle（首期必需）
wget -c "${HF_BASE}/longmemeval_oracle.json" -O "${DATA_DIR}/longmemeval_oracle.json"

# S 版（Phase 2）
wget -c "${HF_BASE}/longmemeval_s_cleaned.json" -O "${DATA_DIR}/longmemeval_s_cleaned.json"

# M 版（暂不下载，1.69GB）
# wget -c "${HF_BASE}/longmemeval_m_cleaned.json" -O "${DATA_DIR}/longmemeval_m_cleaned.json"
```

### 校验

| 文件 | 预期大小 |
|------|---------|
| longmemeval_oracle.json | ~15MB |
| longmemeval_s_cleaned.json | ~277MB |

### .gitignore

```
bench/longmemeval/data/*.json
bench/longmemeval/data/preprocessed/
bench/longmemeval/data/locomo_*/
```

## Ingest 映射

### 会话 → IngestInput

```python
def haystack_session_to_ingest(question_id, session_turns, session_datetime, session_id):
    """LongMemEval 会话 → MCS ingest 输入"""
    lines = []
    for turn in session_turns:
        role = turn['role']  # "user" | "assistant"
        content = turn['content']
        lines.append(f"[{session_datetime}] {role}: {content}")
    return IngestInput(
        content="\n".join(lines),
        timestamp=parse_datetime(session_datetime).isoformat(),  # 字段名 timestamp（非 now），ISO 字符串
        metadata={"doc_id": question_id, "chunk_id": session_id},  # source_tracking session 级溯源
    )
```

### 时间戳解析

```python
def parse_datetime(dt_str: str) -> datetime:
    """解析 LongMemEval 时间戳格式 → datetime，调用方 .isoformat() 传给 IngestInput.timestamp"""
    # "2023/04/10 (Mon) 23:07" → datetime(2023, 4, 10, 23, 7)
    # 去掉星期部分
    clean = re.sub(r'\s*\([^)]+\)', '', dt_str)
    return datetime.strptime(clean, "%Y/%m/%d %H:%M")
```

## 评测流程

```
1. 下载数据（download_data.py）
2. 预处理：解析时间戳、排序会话、拆分类型
3. 对每个问题:
   a. 创建独立 MCS 实例 (SQLite db)
   b. 按时间顺序 ingest 各会话
   c. agent.chat(question) → 生成答案
   d. LLM judge 判对错
   e. 记录结果
4. 聚合指标 → REPORT.md
```

## 横向基线

| 系统 | LongMemEval S 版 | 说明 |
|------|-----------------|------|
| Zep | 90.2% (451/500) | 104ms p50, 4408 median tokens |
| Mem0 | ~70% (估计) | 官方未公布精确数字 |
| Human | - | 论文未报 LongMemEval 人类基线 |
