# MultiHop-RAG 数据文件

本目录存放 MultiHop-RAG 评测数据集。数据文件**不提交到 git**。

## 数据下载

从 HuggingFace `yixuantt/MultiHop-RAG` 下载两个文件：

- `multihoprag_corpus.json` — 609 篇新闻文档（title/body/source/published_at/url/author/category）
- `multihoprag_qa.json` — 2556 个 query（query/answer/question_type/evidence_list）

### 方式一：huggingface-cli

```bash
huggingface-cli download yixuantt/MultiHop-RAG --repo-type dataset --local-dir .
```

### 方式二：网页下载

访问 https://huggingface.co/datasets/yixuantt/MultiHop-RAG 下载后放入本目录。

## 预期文件

```
bench/multihop_rag/data/
├── multihoprag_corpus.json
└── multihoprag_qa.json
```

## 默认路径

评测脚本默认从 `bench/multihop_rag/data/` 读取数据（即本目录）。
