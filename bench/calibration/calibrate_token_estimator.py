"""Token 估算器校准脚本。

用法：
    python -m bench.calibration.calibrate_token_estimator --model deepseek-chat --samples 100

产出：
    - 各模型族的经验式系数（CJK 系数、非 CJK 除数）
    - 经验式 vs 精确计数的偏差统计
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

# ── 样本文本池 ──────────────────────────────────────────────────────────────

CHINESE_SAMPLES = [
    "深度学习是机器学习的一个子领域，它试图使用包含复杂结构或由多重非线性变换构成的多个处理层对数据进行高层抽象的算法。",
    "自然语言处理是人工智能领域中的一个重要方向，它研究能实现人与计算机之间用自然语言进行有效通信的各种理论和方法。",
    "知识图谱是一种用图结构来表示实体及其关系的语义网络，它被广泛应用于搜索引擎、智能问答和推荐系统等场景。",
    "在图神经网络中，消息传递机制允许节点通过聚合邻居信息来更新自身表示，从而捕获图的结构特征。",
    "检索增强生成技术将大语言模型与外部知识库结合，通过检索相关文档来增强模型的生成质量和事实准确性。",
    "注意力机制使得模型能够动态地关注输入序列中的不同部分，在翻译和摘要等任务中取得了显著效果。",
    "对比学习通过拉近正样本对、推远负样本对来学习表示，在自监督学习中被广泛使用。",
    "知识蒸馏是一种模型压缩技术，它让小模型（学生）模仿大模型（教师）的输出分布来提升性能。",
    "多跳推理要求模型能够跨越多个文档或知识片段进行推理，是问答系统中的核心挑战之一。",
    "图注意力网络将注意力机制引入图神经网络，为不同邻居节点分配不同权重，提升了节点分类的准确率。",
]

MIXED_SAMPLES = [
    "Transformer 架构使用 self-attention 机制替代了 RNN 的递归结构，使得模型可以并行处理序列数据。",
    "GPT（Generative Pre-trained Transformer）系列模型通过自回归方式生成文本，在 zero-shot 和 few-shot 学习中表现优异。",
    "BERT 采用 Masked Language Model（MLM）预训练策略，通过预测被遮蔽的 token 来学习双向上下文表示。",
    "RAG（Retrieval-Augmented Generation）框架将检索模块和生成模块结合，先从知识库检索相关段落，再输入 LLM 生成回答。",
    "LoRA（Low-Rank Adaptation）通过在 Transformer 层旁路添加低秩矩阵来实现参数高效微调，显著降低了训练成本。",
    "Chain-of-Thought（CoT）提示技术通过引导 LLM 逐步推理来提升复杂问题的求解能力。",
    "Faiss 是 Meta 开源的高效向量相似性搜索库，支持十亿级向量的快速近邻检索。",
    "Prompt Engineering 通过精心设计输入提示来引导 LLM 产生期望输出，无需修改模型参数。",
    "Embedding 模型将文本映射为稠密向量，使得语义相近的文本在向量空间中距离更近。",
    "Tokenization 是 NLP 的基础步骤，BPE（Byte Pair Encoding）算法通过合并高频字节对来构建词表。",
]

ENGLISH_SAMPLES = [
    "Large language models have demonstrated remarkable capabilities in natural language understanding and generation tasks.",
    "Retrieval-augmented generation combines the strengths of retrieval-based and generation-based approaches for knowledge-intensive tasks.",
    "Graph neural networks operate on graph-structured data by propagating and aggregating information along edges between nodes.",
    "The attention mechanism allows neural networks to focus on relevant parts of the input, enabling better performance on sequence tasks.",
    "Transfer learning enables models trained on large datasets to be fine-tuned for specific downstream tasks with minimal additional data.",
    "Knowledge graphs store structured information as triples of entities and relations, supporting reasoning and question answering.",
    "Contrastive learning learns representations by pulling positive pairs closer and pushing negative pairs apart in embedding space.",
    "Parameter-efficient fine-tuning methods like LoRA reduce the computational cost of adapting large pre-trained models.",
    "Multi-hop reasoning requires integrating information from multiple sources or reasoning steps to answer complex questions.",
    "Vector databases enable efficient similarity search over high-dimensional embeddings, powering modern RAG systems.",
]


def generate_samples(n: int = 100) -> list[dict]:
    """生成中英混合样本集。

    Returns:
        list of {"text": str, "lang": "zh"|"mix"|"en"}
    """
    samples = []
    n_zh = n // 2
    n_mix = int(n * 0.3)
    n_en = n - n_zh - n_mix

    for _ in range(n_zh):
        base = random.choice(CHINESE_SAMPLES)
        # 随机重复或截断以生成不同长度
        factor = random.choice([0.5, 1, 1.5, 2, 3])
        if factor < 1:
            text = base[: int(len(base) * factor)]
        else:
            text = "。".join([base] * int(factor))
        samples.append({"text": text, "lang": "zh"})

    for _ in range(n_mix):
        base = random.choice(MIXED_SAMPLES)
        factor = random.choice([0.5, 1, 1.5, 2, 3])
        if factor < 1:
            text = base[: int(len(base) * factor)]
        else:
            text = "。 ".join([base] * int(factor))
        samples.append({"text": text, "lang": "mix"})

    for _ in range(n_en):
        base = random.choice(ENGLISH_SAMPLES)
        factor = random.choice([0.5, 1, 1.5, 2, 3])
        if factor < 1:
            text = base[: int(len(base) * factor)]
        else:
            text = ". ".join([base] * int(factor))
        samples.append({"text": text, "lang": "en"})

    return samples


def count_with_tiktoken(text: str, encoding_name: str = "cl100k_base") -> int:
    """使用 tiktoken 精确计数。"""
    import tiktoken

    enc = tiktoken.get_encoding(encoding_name)
    return len(enc.encode(text))


def count_with_claude_api(text: str, model: str, api_key: str) -> int:
    """使用 Anthropic count_tokens API 计数。"""
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    resp = client.messages.count_tokens(
        model=model,
        messages=[{"role": "user", "content": text}],
    )
    return resp.input_tokens


def evaluate_estimator(
    samples: list[dict],
    true_counts: list[int],
    model_family: str,
) -> dict:
    """评估校准经验式与精确计数的偏差。

    Returns:
        {
            "model_family": str,
            "cjk_coeff": float,
            "non_cjk_divisor": int,
            "mean_ratio": float,   # 经验式/精确 的均值
            "underestimate_pct": float,  # 低估比例
            "max_underestimate_ratio": float,  # 最大低估偏差
            "samples": int,
        }
    """
    from mcs.core.calibrated_estimator import CalibratedEstimator

    est = CalibratedEstimator(model_family)
    ratios = []
    under_count = 0
    max_under_ratio = 0.0

    for sample, true_count in zip(samples, true_counts):
        est_count = est.estimate(sample["text"])
        if true_count > 0:
            ratio = est_count / true_count
            ratios.append(ratio)
            if est_count < true_count:
                under_count += 1
                under_ratio = (true_count - est_count) / true_count
                max_under_ratio = max(max_under_ratio, under_ratio)

    return {
        "model_family": model_family,
        "cjk_coeff": est._cjk_coeff,
        "non_cjk_divisor": est._non_cjk_divisor,
        "mean_ratio": sum(ratios) / len(ratios) if ratios else 0,
        "underestimate_pct": under_count / len(samples) * 100 if samples else 0,
        "max_underestimate_ratio": max_under_ratio,
        "samples": len(samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="校准 token 估算器的经验式系数"
    )
    parser.add_argument(
        "--model",
        default="deepseek-chat",
        help="模型名称（用于选择计数方案）",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=100,
        help="样本数量（默认 100）",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key（Claude 模型需要）",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出文件路径（默认 stdout）",
    )
    args = parser.parse_args()

    # 1. 生成样本
    random.seed(42)
    samples = generate_samples(args.samples)
    print(f"生成 {len(samples)} 个样本（zh={sum(1 for s in samples if s['lang']=='zh')} "
          f"mix={sum(1 for s in samples if s['lang']=='mix')} "
          f"en={sum(1 for s in samples if s['lang']=='en')}）")

    # 2. 精确计数
    true_counts = []
    model_lower = args.model.lower()

    if "claude" in model_lower:
        if not args.api_key:
            print("错误：Claude 模型需要 --api-key 参数", file=sys.stderr)
            sys.exit(1)
        for s in samples:
            true_counts.append(count_with_claude_api(s["text"], args.model, args.api_key))
    else:
        # DeepSeek / Ollama / 其他：使用 tiktoken cl100k_base
        for s in samples:
            true_counts.append(count_with_tiktoken(s["text"]))

    # 3. 评估各模型族的经验式
    results = []
    for family in ["claude", "gpt", "deepseek", "ollama", "unknown"]:
        result = evaluate_estimator(samples, true_counts, family)
        results.append(result)
        print(
            f"  {family:10s}: 均值比={result['mean_ratio']:.2f} "
            f"低估率={result['underestimate_pct']:.1f}% "
            f"最大低估={result['max_underestimate_ratio']:.1%}"
        )

    # 4. 输出
    output = {
        "model": args.model,
        "samples": len(samples),
        "results": results,
    }
    if args.output:
        Path(args.output).write_text(json.dumps(output, indent=2, ensure_ascii=False))
        print(f"\n结果已保存到 {args.output}")
    else:
        print("\n" + json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
