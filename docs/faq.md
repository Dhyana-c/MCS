# 常见问题（FAQ）

## 通用

### MCS 是什么？

MCS（Maximum-Context Subgraph）是一个可扩展的记忆系统——面向单一领域，由大模型语义驱动，把零散文本组织成图结构的语义记忆。不依赖 embedding / 向量检索。

### MCS 返回什么？

MCS 默认返回相关节点集合（`List[Node]`），不是自然语言答案。它专注于"记忆本身"，把合成答案、多轮对话等留给上层。

### "核心赌注"是什么意思？

核心假设是**知识有足够的局部性**——回答一个问题所需要的概念，在图里彼此靠近，几跳语义游走就能连到一起。这对已能被人类整理成可教结构的领域（物理、工程、各类有教科书/本体的学科）最成立。

## 使用

### 支持哪些 LLM 后端？

Phase 1 支持三种：
- **DeepSeek**：默认后端，OpenAI SDK 兼容
- **Claude / Anthropic**：可选，`pip install -e ".[claude]"`
- **Ollama**：本地推理，零 token 成本，需单独安装

### 需要 API key 吗？

可以不需要。`examples/` 下的示例默认走 mock 模式。使用 Ollama 本地后端也不需要 API key。使用 DeepSeek / Claude 后端需要对应的 API key。

### 如何切换 LLM 后端？

```python
# DeepSeek（默认）
mcs = create_mcs(llm="deepseek", db_path="mcs.db")

# Claude
mcs = create_mcs(llm="claude", db_path="mcs.db")

# Ollama（本地）
mcs = create_mcs(llm="ollama", db_path="mcs.db")
```

### 数据如何持久化？

MCS 默认开启自动落盘（`auto_persist=True`），使用 SQLite。每次 `ingest()` 完成后自动持久化。Builder 在 `build()` 时会自动从数据库加载已有数据。

## 设计

### 为什么不用向量检索？

MCS 的核心赌注是知识有局部性，不需要向量相似度兜底。大模型直接阅读"装得下的局部子图"做判断，比向量相似度更准确（尤其在关系发现、聚类场景）。

### "最大上下文子图不变量"是什么？

任意节点 + 它的全部一跳子节点，渲染成 LLM 输入的 token 数 ≤ 一个上下文窗口 T。这是导航、归纳、查询的共同地基——保证 LLM 永远能一次性读完任意节点的局部视野。

### 为什么只有单向边？

全图只有单向边 `source → target`。语义关系用两条对向单向边表达（`a→b` + `b→a`），保持双向可达性。层级关系为纯下行单向边 `父→子`。这样做让导航方向清晰，避免缠绕成环。

## 评测

### 评测指标是什么？

MultiHop-RAG 评测的指标为文档级检索：**Hit@k / Recall@k / MAP@k / MRR@k**。`query()` 返回的节点经 `source_tracking` 映射回来源文档，与 gold evidence 文档比对。

### 相关性重排为什么重要？

查询管线默认按 BFS 发现顺序返回（无排序），gold 文档常被埋没。开启查询侧词法重排（现为默认、零额外 LLM 调用）后，overall Hit@10 从 ~0.16 提升到 ~0.73。

## 进一步阅读

- [架构总览](architecture.md) — 系统定位、双层结构、插件体系
- [核心流程](core-flows.md) — 读写管线、图演化
- [技术方案](technical-design.md) — 完整的机制设计文档
