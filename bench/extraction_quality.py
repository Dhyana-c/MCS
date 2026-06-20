"""概念/事实抽取准确率评测。

评测 extract_concepts prompt 区分概念 vs 事实的准确率。
需要标注数据集（JSONL 格式），每条包含：
  - text: 原始输入文本
  - expected: 期望抽取结果列表，每项含 name, content, node_class

用法:
  python -m bench.extraction_quality --dataset data/extraction_samples.jsonl

指标：
  - precision: 抽出的 node_class 正确率（概念被标为概念 / 事实被标为事实）
  - recall: 期望条目被抽出的比例
  - f1: precision × recall 的调和平均

Phase 1: 手工小样本验证（~20 条），确认 prompt 方向正确。
Phase 2: 扩大样本 + 引入转述嵌套测试（"读到的/听说的/书里的"不污染时间轴）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExtractionSample:
    """一条评测样本。"""

    text: str
    expected: list[dict[str, str]]  # [{"name": ..., "content": ..., "node_class": "概念"|"事实"}]


@dataclass
class ExtractionMetrics:
    """抽取评测指标。"""

    total: int = 0
    correct_class: int = 0  # node_class 判对
    extracted: int = 0  # 被成功抽出
    expected: int = 0  # 期望抽出数

    @property
    def precision(self) -> float:
        return self.correct_class / self.extracted if self.extracted else 0.0

    @property
    def recall(self) -> float:
        return self.extracted / self.expected if self.expected else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def load_samples(path: Path) -> list[ExtractionSample]:
    """从 JSONL 加载评测样本。"""
    samples = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        samples.append(ExtractionSample(text=d["text"], expected=d["expected"]))
    return samples


def evaluate_extraction(
    samples: list[ExtractionSample],
    extract_fn: Any,  # callable(text) -> list[dict]
) -> ExtractionMetrics:
    """运行抽取并计算指标。

    Args:
        samples: 评测样本列表
        extract_fn: 抽取函数，接收文本返回 [{"name": ..., "node_class": ...}]
    """
    metrics = ExtractionMetrics()
    for sample in samples:
        metrics.expected += len(sample.expected)
        try:
            results = extract_fn(sample.text)
        except Exception:
            logger.warning("抽取失败: %s...", sample.text[:50], exc_info=True)
            continue

        metrics.extracted += len(results)
        # 简化匹配：按 name 匹配，比对 node_class
        expected_by_name = {e["name"]: e for e in sample.expected}
        for r in results:
            name = r.get("name", "")
            if name in expected_by_name:
                if r.get("node_class") == expected_by_name[name].get("node_class"):
                    metrics.correct_class += 1
        metrics.total += 1

    return metrics
