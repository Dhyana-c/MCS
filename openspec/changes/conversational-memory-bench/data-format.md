# locomo-bench spec

## 数据格式

### LoCoMo V2 Base (`locomo_v2_base.json`)

```json
[
  {
    "sample_id": "conv-26",
    "conversation": {
      "speaker_a": "Sarah",
      "speaker_b": "Jessica",
      "session_1_date_time": "1:56 pm on 8 May, 2023",
      "session_1": [
        {"speaker": "Sarah", "dia_id": "D1:3", "text": "..."},
        {"speaker": "Jessica", "dia_id": "D1:4", "text": "...", "img_url": ["..."]}
      ],
      "session_2_date_time": "...",
      "session_2": [...]
    },
    "qa": [
      {"question": "...", "answer": "...", "category": 2},
      {"question": "...", "category": 5, "adversarial_answer": "..."}
    ]
  }
]
```

**注意（实测）**：V2 base 的 turn **没有 caption**（910 个带 `img_url` 的轮次 caption 全空）——从 V2 caption 变体移植（见下）。

### V2 caption 变体（`locomo_v2_{moondream,qwen,minicpm}.json`）

conversation 文本与 base **逐轮零差异**（实测），带图轮次多一个 `{model}_caption` 字段（VLM 深度 caption、含 OCR）。caption 覆盖 834/910 带图轮（缺失 76 轮 = 永久死链图像，V2 官方判定依赖它们的 63 题不可解）。均长：moondream 438 字符 / minicpm 787 / qwen 982。**默认取 moondream**（OCR 在线 + 最短），config `caption_variant` 可切。
另有 `locomo_v2_{local,web}.json` 为图像 URL 重写变体（本地路径 / GitHub 存档），供真多模态管线重下图像，本评测不用。

### LoCoMo V1 Source (`locomo_v1_source.json`)

同 V2 结构，但：
- QA 条目含 `evidence` 字段：`{"question": "...", "answer": "...", "evidence": ["D1:3", "D2:8"], "category": 1}`——注意 **Multi-Mention Flaw**：只标事实首次提及处（V2 因此有意删除 evidence，主张端到端 judge）
- turn 含 `blip_caption`（1226 轮，BLIP 无 OCR，**弃用**）与 `query`（图像检索词）字段
- **人物名是 V1 旧名**（见下节换名映射）——V2 换名是有意**去污染**（防 LLM 预训练记忆背答案）；V1 仅用于 evidence 移植

### V1 → V2 换名映射（实测，从 `speaker_a/b` 字段机械建立）

V2 把全部人物换名（conversation 文本 2072 处 turn 改动均为人名替换，dia_id 集合两版一致）：

| sample_id | speaker_a | speaker_b |
|-----------|-----------|-----------|
| conv-26 | Caroline→Sarah | Melanie→Jessica |
| conv-30 | Jon→Joel | Gina→Grace |
| conv-41 | John→Jack | Maria→Mia |
| conv-42 | Joanna→Julia | Nate→Noah |
| conv-43 | Tim→Tom | John→Jack |
| conv-44 | Audrey→Alice | Andrew→Arthur |
| conv-47 | James→Jacob | John→Jack |
| conv-48 | Deborah→Diana | Jolene→Jasmine |
| conv-49 | Evan→Ethan | Sam→Seth |
| conv-50 | Calvin→Connor | Dave→Derek |

### 三源合成规则（D1）

1. **主体**：V2 conversation + QA（建图语料与评测问题统一用 V2 人名——V1 问题查 V2 图人名对不上，禁止混用）
2. **caption 移植**：按 `dia_id` 从 V2 caption 变体（默认 moondream）逐轮取 `{model}_caption`（移植前校验变体 conversation 与 base 逐轮 text 一致）；834 轮
3. **evidence 移植**：V1 问题文本经换名映射（词边界替换）→ 与 V2 问题精确匹配（大小写不敏感）→ 命中者挂 V1 `evidence`。实测 1881/1922 = 98% 命中；未命中 41 题只走 QA 轨。evidence 有 Multi-Mention Flaw，检索轨仅作诊断副指标

### 类别映射（从实测数据钉死）

| Category | 名称 | 语义特征 | V1 数量 | V2 数量 |
|----------|------|---------|---------|---------|
| 1 | multi-hop | 跨 session 证据 | 282 | 261 |
| 2 | temporal | 答案含时间/日期 | 321 | 308 |
| 3 | open-domain | 推理/偏好 | 96 | 94 |
| 4 | single-hop | 单证据点 | 841 | 821 |
| 5 | adversarial | 错误归因（弃答=正确） | 446 | 438 |
| **Total** | | | **1986** | **1922** |

**类别映射验证方法**：从 V1 source 按 category 数一遍 + 每类抽 5 样本核对语义特征。Cat 4 是最大类（~841/821），语义为 single-hop（单证据点、短答案），**不是 inference**。

### 对话统计（实测 V2）

| 指标 | 值 |
|------|-----|
| 对话数 | 10（conv-26/30/41/42/43/44/47/48/49/50） |
| 每对话会话数 | 19-32（avg 27.2，总 272） |
| 每对话轮次数 | 369-689（avg 588，总 5882） |
| 每对话文本量 | avg ~72.6K 字符 ≈ ~18K token（总 ~182K token） |
| 带图轮次 | 910（img_url）；VLM caption 覆盖 834（76 轮死链无 caption） |
| 总 QA 数 | 1986 (V1) / 1922 (V2)；移植 evidence 后检索轨 1881 |

## 数据拉取流程

### 下载脚本

```bash
# bench/locomo/scripts/download_data.py

DATA_DIR="bench/locomo/data"

# 第 0 步：探测复用——本机既有 clone（历史落位）存在且校验通过则移动，不重复下载
#   bench/longmemeval/data/locomo_repo → ${DATA_DIR}/locomo_repo
#   bench/longmemeval/data/locomo_v2  → ${DATA_DIR}/locomo_v2

# V1 官方数据（含 locomo10.json + 生成管线 + 评测代码）
git clone --depth 1 https://github.com/snap-research/locomo.git "${DATA_DIR}/locomo_repo"

# V2 社区修正版（含 locomo_v2_base.json + locomo_v1_source.json）
git clone --depth 1 https://github.com/BrianV1981/locomo-v2.git "${DATA_DIR}/locomo_v2"
# V2 仓库含 Windows Zone.Identifier 文件，checkout 可能失败，需手动 restore
cd "${DATA_DIR}/locomo_v2" && git restore --source=HEAD :/ 2>/dev/null || true
```

### 数据文件位置

| 文件 | 路径 | 大小 | 说明 |
|------|------|------|------|
| V1 主数据 | `locomo_repo/data/locomo10.json` | 2.8MB | 10 对话，1986 题（含 evidence） |
| V2 base | `locomo_v2/data/locomo_v2_base.json` | 2.5MB | 10 对话，1922 题（修正答案 + 去污染换名，无 evidence/caption）——**语料与 QA 主体** |
| V2 caption 变体 | `locomo_v2/data/locomo_v2_{moondream,qwen,minicpm}.json` | 2.9-3.4MB | conversation 同 base + VLM caption（834 轮）——**caption 移植源**（默认 moondream） |
| V1 source | `locomo_v2/data/locomo_v1_source.json` | 2.8MB | 10 对话，1986 题（含 evidence，V2 仓库提供）——**仅 evidence 移植源** |
| URL 重写变体 | `locomo_v2/data/locomo_v2_{local,web}.json` | 2.5MB | 图像 URL 指向本地/GitHub 存档，供真多模态管线，本评测不用 |

### 校验

| 文件 | 预期大小 |
|------|---------|
| locomo10.json | ~2.8MB |
| locomo_v2_base.json | ~2.5MB |
| locomo_v1_source.json | ~2.8MB |

### .gitignore

```
bench/locomo/data/locomo_repo/
bench/locomo/data/locomo_v2/
bench/locomo/data/preprocessed/
```

## Ingest 映射

### 会话 → IngestInput（双轨事件）

```python
def session_to_ingest(sample_id, session_n, session_turns, session_datetime):
    """LoCoMo 会话 → MCS ingest 输入。

    - work_id=sample_id：触发 ③b 作品叙事事件抽取（谈话中的事件 → 对话 universe 叙事时间轴）
    - timestamp=会话时间：摄入行为事件（当下事件 → __reality__ 时间轴）
    - metadata doc_id/chunk_id：source_tracking 记 session 级溯源（检索轨映射用）
    """
    lines = []
    for turn in session_turns:
        prefix = f"[{session_datetime}] {turn['speaker']}: "
        text = turn['text']
        if turn.get('caption'):  # V2 caption 变体移植（默认 moondream_caption）
            text += f" [shared image: {turn['caption']}]"
        lines.append(prefix + text)
    return IngestInput(
        content="\n".join(lines),
        timestamp=parse_datetime(session_datetime).isoformat(),  # 字段名 timestamp（非 now），ISO 字符串
        work_id=sample_id,
        metadata={"doc_id": sample_id, "chunk_id": f"session_{session_n}"},
    )
```

### 时间戳解析

```python
def parse_datetime(dt_str: str) -> datetime:
    """解析 LoCoMo 时间戳格式 → datetime，调用方 .isoformat() 传给 IngestInput.timestamp"""
    # "1:56 pm on 8 May, 2023" → datetime(2023, 5, 8, 13, 56)
    return datetime.strptime(dt_str, "%I:%M %p on %d %B, %Y")
```

## 检索轨映射（session 级，经 source_tracking）

```python
def dia_id_to_session_id(dia_id: str) -> int:
    """D{N}:M → session 编号 N（session 级，不做 turn 级）"""
    return int(dia_id.split(":")[0][1:])

def compute_recall_at_k(query_nodes, question, k_values=(5, 10, 20)):
    """计算 session 级 Recall@k"""
    # 1. gold session 集合（来自移植的 V1 evidence）
    gold = {dia_id_to_session_id(e) for e in question.evidence}
    # 2. 召回 session 序列：按节点 rank 顺序取 source_tracking.sources 的
    #    chunk_id（"session_N"），去重保序——ingest 时经 metadata 写入，无需模糊匹配
    retrieved = dedup_keep_order(
        int(s.chunk_id.removeprefix("session_"))
        for node in query_nodes
        for s in node.extensions["source_tracking"]["sources"]
    )
    # 3. 召回
    for k in k_values:
        top_k = set(retrieved[:k])
        hit_any = bool(gold & top_k)   # any-evidence hit（主）
        hit_all = gold <= top_k        # all-evidence hit（副）
```

## 评测流程

```
1. 下载数据（download_data.py，优先探测复用既有 clone）
2. 三源合成 + 预处理：换名映射、caption/evidence 移植、解析时间戳、排序会话、拆分类型
3. 对每个对话:
   a. 创建独立 MCS 实例 (SQLite db)
   b. 按时间顺序 ingest 各会话 (timestamp=会话时间, work_id=sample_id, metadata={doc_id, chunk_id})
      → 当下事件落 __reality__；③b 抽谈话中的事件落对话 universe 叙事时间轴
   c. 对每个 QA:
      - QA 轨: agent.chat(question)（temporal 题提示用 timeline(universe=对话)）→ LLM judge 判定（主指标）
      - 检索轨（有移植 evidence 的题）: mcs.query(question) → session 级 Recall@k
      - 记录结果
4. 聚合指标 → REPORT.md
```

## 横向基线（逐行注明口径）

| 系统 | 整体 | 口径 | 说明 |
|------|------|------|------|
| Zep | 94.7% | LLM-judge | top-200 检索 + GPT 生成 + judge |
| Mem0 | 92.5% | LLM-judge | **排除 adversarial 类** |
| Human | 87.9 F1 | token-F1 | 论文原始口径，与 LLM-judge 不可直接比 |
| MCS | ? | LLM-judge | 本评测主指标，与 Zep/Mem0 可直接比 |

**注意**：三种口径（LLM-judge / token-F1 / 时间容忍 F1）不可混比。主表只放 LLM-judge 口径数字；F1 和时间容忍单列副表。
