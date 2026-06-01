"""HotpotQA 评测框架测试。"""

from __future__ import annotations

import json
import pytest
from dataclasses import asdict
from unittest.mock import MagicMock, patch

from mcs.bench.hotpot import (
    HotpotDataLoader,
    HotpotEvalConfig,
    HotpotEvalRunner,
    HotpotItem,
    extract_answer,
    extract_prediction,
    extract_supporting_facts,
    format_context_paragraph,
    ingest_hotpot_item,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_hotpot_raw():
    """样例 HotpotQA 原始数据。"""
    return [
        {
            "_id": "test_001",
            "question": "Were Scott Derrickson and Ed Wood of the same nationality?",
            "answer": "no",
            "supporting_facts": [
                ["Scott Derrickson", "0"],
                ["Ed Wood", "0"],
            ],
            "context": [
                ["Scott Derrickson", ["Scott Derrickson is an American filmmaker."]],
                ["Ed Wood", ["Ed Wood was an American filmmaker and actor."]],
                ["Other", ["This is a distractor paragraph."]],
            ],
            "type": "comparison",
            "level": "hard",
        },
        {
            "_id": "test_002",
            "question": "What genre is The Matrix?",
            "answer": "science fiction",
            "supporting_facts": [["The Matrix", "0"]],
            "context": [
                ["The Matrix", ["The Matrix is a science fiction action film."]],
                ["Other", ["Distractor."]],
            ],
            "type": "bridge",
            "level": "hard",
        },
    ]


@pytest.fixture
def sample_hotpot_file(tmp_path, sample_hotpot_raw):
    """创建临时 HotpotQA JSON 文件。"""
    f = tmp_path / "hotpot_test.json"
    f.write_text(json.dumps(sample_hotpot_raw), encoding="utf-8")
    return str(f)


# ─── 7.1 测试 HotpotDataLoader 分层采样 ───────────────────────────────────────


def test_load_full_set(sample_hotpot_file):
    """测试加载全量数据。"""
    loader = HotpotDataLoader(sample_hotpot_file, subset=None)
    items = loader.load()
    assert len(items) == 2
    assert all(isinstance(it, HotpotItem) for it in items)


def test_load_subset(sample_hotpot_file):
    """测试采样子集。"""
    loader = HotpotDataLoader(sample_hotpot_file, subset=1)
    items = loader.load()
    # 样例只有 2 条且跨 2 个 type，uniform 策略会保证每个 type 至少 1 条
    # 所以 subset=1 时实际可能返回 2 条（每个 type 1 条）
    assert len(items) >= 1


def test_stratified_sampling_uniform(sample_hotpot_file):
    """测试 uniform 分层采样：每个 type 都有覆盖。"""
    loader = HotpotDataLoader(sample_hotpot_file, subset=2, sample_strategy="uniform")
    items = loader.load()
    types = {it.type for it in items}
    # 样例有 bridge 和 comparison，uniform 应该都覆盖
    assert "bridge" in types
    assert "comparison" in types


def test_stratified_sampling_proportional(sample_hotpot_file):
    """测试 proportional 分层采样。"""
    loader = HotpotDataLoader(
        sample_hotpot_file, subset=2, sample_strategy="proportional"
    )
    items = loader.load()
    assert len(items) <= 2


def test_hotpot_item_fields(sample_hotpot_file):
    """测试 HotpotItem 字段。"""
    loader = HotpotDataLoader(sample_hotpot_file, subset=None)
    items = loader.load()
    item = items[0]
    assert hasattr(item, "_id")
    assert hasattr(item, "question")
    assert hasattr(item, "answer")
    assert hasattr(item, "supporting_facts")
    assert hasattr(item, "context")
    assert hasattr(item, "type")
    assert hasattr(item, "level")


# ─── 7.2 测试 context 格式化和 ingest ────────────────────────────────────────


def test_format_context_paragraph():
    """测试段落格式化。"""
    title = "The Matrix"
    sentences = ["The Matrix is a 1999 film.", "It was directed by the Wachowskis."]
    result = format_context_paragraph(title, sentences)
    assert result == "The Matrix: The Matrix is a 1999 film. It was directed by the Wachowskis."


def test_format_context_paragraph_single():
    """测试单句段落格式化。"""
    title = "Test"
    sentences = ["Single sentence."]
    result = format_context_paragraph(title, sentences)
    assert result == "Test: Single sentence."


def test_ingest_hotpot_item_creates_isolated_instance(sample_hotpot_raw):
    """测试 ingest 创建独立 MCS 实例。"""
    item = HotpotItem(**sample_hotpot_raw[0])
    # Mock MCS 和 MCSConfig 在 mcs 模块中
    with patch("mcs.MCS") as mock_mcs_cls:
        mock_instance = MagicMock()
        mock_mcs_cls.return_value = mock_instance

        result = ingest_hotpot_item(item, llm="deepseek")

        # 验证 MCS 被初始化
        mock_mcs_cls.assert_called_once()
        mock_instance.initialize.assert_called_once()

        # 验证 ingest 被调用 context 长度次
        assert mock_instance.ingest.call_count == len(item.context)


def test_ingest_skips_failing_paragraph(sample_hotpot_raw):
    """单段 ingest 抛错时应跳过该段、继续其余段，不向上抛出。"""
    item = HotpotItem(**sample_hotpot_raw[0])  # 3 段
    with patch("mcs.MCS") as mock_mcs_cls:
        inst = MagicMock()
        mock_mcs_cls.return_value = inst
        inst.ingest.side_effect = [None, RuntimeError("boom"), None]
        result = ingest_hotpot_item(item, llm="deepseek")
        assert result is inst
        assert inst.ingest.call_count == 3  # 仍尝试了全部 3 段


# ─── 7.3 测试 answer 和 supporting_facts 提取 ────────────────────────────────


def test_extract_answer_yes():
    """测试 yes 答案提取（需 yes/no 句式问题）。"""
    mock_node = MagicMock()
    mock_node.name = "Yes"
    mock_node.content = "The answer is yes."
    result = extract_answer([mock_node], "Were they the same nationality?")
    assert result == "yes"


def test_extract_answer_no():
    """测试 no 答案提取（需 yes/no 句式问题）。"""
    mock_node = MagicMock()
    mock_node.name = "No"
    mock_node.content = "The answer is no."
    result = extract_answer([mock_node], "Is it the same?")
    assert result == "no"


def test_extract_answer_wh_question_not_coerced_to_yesno():
    """wh- 问题即使节点含 'no' 也不应被误判为 yes/no（验证 yes/no 门控）。"""
    mock_node = MagicMock()
    mock_node.name = "Bela Lugosi"
    mock_node.content = "He had no formal training."
    result = extract_answer([mock_node], "Who played the actor?")
    assert result == "Bela Lugosi"


def test_extract_answer_entity():
    """测试实体答案提取。"""
    mock_node = MagicMock()
    mock_node.name = "The Matrix"
    mock_node.content = "The Matrix is a film."
    result = extract_answer([mock_node])
    assert result == "The Matrix"


def test_extract_answer_empty():
    """测试空节点列表。"""
    result = extract_answer([])
    assert result == ""


def test_extract_supporting_facts():
    """测试 supporting facts 提取。"""
    mock_node = MagicMock()
    mock_node.extensions = {
        "source_tracking": {
            "sources": [
                MagicMock(section_title="Scott Derrickson"),
                MagicMock(section_title="Ed Wood"),
            ]
        }
    }
    result = extract_supporting_facts([mock_node])
    assert len(result) == 2
    assert result[0] == ["Scott Derrickson", 0]
    assert result[1] == ["Ed Wood", 0]


def test_extract_supporting_facts_dedup():
    """测试 supporting facts 去重。"""
    mock_node = MagicMock()
    mock_node.extensions = {
        "source_tracking": {
            "sources": [
                MagicMock(section_title="Scott Derrickson"),
                MagicMock(section_title="Scott Derrickson"),
            ]
        }
    }
    result = extract_supporting_facts([mock_node])
    assert len(result) == 1


def test_extract_supporting_facts_empty():
    """测试空节点列表。"""
    result = extract_supporting_facts([])
    assert result == []


def test_extract_supporting_facts_top_n_prunes():
    """5.7：按 node rank 取 top-N，超出的来源 title 被剪掉。"""
    nodes = []
    for t in ["A", "B", "C", "D"]:
        n = MagicMock()
        n.extensions = {"source_tracking": {"sources": [MagicMock(section_title=t)]}}
        nodes.append(n)
    assert extract_supporting_facts(nodes, top_n=2) == [["A", 0], ["B", 0]]
    # top_n=None 保留旧行为：吐出全部去重 title
    assert len(extract_supporting_facts(nodes, top_n=None)) == 4


def test_extract_prediction_respects_sp_top_n():
    """5.7：extract_prediction 把 sp_top_n 透传给 supporting-facts 剪枝。"""
    nodes = []
    for t in ["A", "B", "C"]:
        n = MagicMock()
        n.name = "ans"
        n.content = ""
        n.extensions = {"source_tracking": {"sources": [MagicMock(section_title=t)]}}
        nodes.append(n)
    pred = extract_prediction(nodes, "id1", "What is it?", sp_top_n=1)
    assert pred["sp"] == [["A", 0]]


def test_extract_prediction():
    """测试整合预测提取。"""
    mock_node = MagicMock()
    mock_node.name = "The Matrix"
    mock_node.content = "The Matrix is a film."
    mock_node.extensions = {
        "source_tracking": {"sources": [MagicMock(section_title="The Matrix")]}
    }
    result = extract_prediction([mock_node], "test_id", "What is The Matrix?")
    assert result["_id"] == "test_id"
    assert result["answer"] == "The Matrix"
    assert result["sp"] == [["The Matrix", 0]]


# ─── 7.4 测试评测运行器（使用 mock LLM）──────────────────────────────────────


def test_eval_runner_dry_run(sample_hotpot_file):
    """测试 dry-run 模式。"""
    config = HotpotEvalConfig(
        data_path=sample_hotpot_file,
        subset=2,
        dry_run=True,
    )
    runner = HotpotEvalRunner(config)
    result = runner.dry_run()
    assert "n_items" in result
    assert "total_tokens_estimated" in result
    assert "estimated_cost_usd" in result
    assert result["n_items"] == 2


def test_run_persists_and_resumes(sample_hotpot_file, tmp_path):
    """run() 增量落盘 predictions.json；resume 复用之，不重复 ingest、指标一致。"""
    out = tmp_path / "out"
    cfg = HotpotEvalConfig(
        data_path=sample_hotpot_file,
        subset=None,
        output_dir=str(out),
        eval_script_dir=str(tmp_path),  # 无 eval 脚本 → 走 fallback 指标
    )

    def fake_ingest(item, llm="deepseek"):
        inst = MagicMock()
        node = MagicMock()
        node.name = item.answer
        node.content = ""
        node.extensions = {
            "source_tracking": {
                "sources": [MagicMock(section_title=item.supporting_facts[0][0])]
            }
        }
        inst.query.return_value = [node]
        return inst

    with patch("mcs.bench.hotpot.ingest_hotpot_item", side_effect=fake_ingest):
        metrics = HotpotEvalRunner(cfg).run()

    saved = json.loads((out / "predictions.json").read_text(encoding="utf-8"))
    assert set(saved["answer"]) == {"test_001", "test_002"}
    assert metrics["em"] >= 0.5

    # 二次运行：resume 跳过全部，不再 ingest，指标一致
    with patch("mcs.bench.hotpot.ingest_hotpot_item") as p2:
        metrics2 = HotpotEvalRunner(cfg).run()
        p2.assert_not_called()
    assert metrics2["em"] == metrics["em"]


def test_eval_runner_config_defaults():
    """测试默认配置。"""
    config = HotpotEvalConfig()
    assert config.subset == 100
    assert config.sample_strategy == "uniform"
    assert config.llm_backend == "deepseek"
    assert config.dry_run is False
    assert config.resume is True


def test_eval_runner_fallback_metrics():
    """测试 fallback 指标计算。"""
    predictions_answer = {"test_001": "no", "test_002": "science fiction"}
    predictions_sp = {
        "test_001": [["Scott Derrickson", 0], ["Ed Wood", 0]],
        "test_002": [["The Matrix", 0]],
    }
    gold_items = [
        HotpotItem(
            _id="test_001",
            question="?",
            answer="no",
            supporting_facts=[["Scott Derrickson", "0"], ["Ed Wood", "0"]],
            context=[],
            type="comparison",
            level="hard",
        ),
        HotpotItem(
            _id="test_002",
            question="?",
            answer="science fiction",
            supporting_facts=[["The Matrix", "0"]],
            context=[],
            type="bridge",
            level="hard",
        ),
    ]
    metrics = HotpotEvalRunner._fallback_metrics(
        predictions_answer, predictions_sp, gold_items
    )
    assert "em" in metrics
    assert "f1" in metrics
    assert "sp_em" in metrics
    assert "sp_f1" in metrics
    assert "joint_em" in metrics
    assert "joint_f1" in metrics
    # 完美预测应该得高分
    assert metrics["em"] >= 0.5
    assert metrics["sp_em"] >= 0.5


def test_compute_metrics_official_perfect_scores():
    """完美预测在官方口径下应满分（验证 12 键聚合 + sp int 下标匹配）。"""
    runner = HotpotEvalRunner(HotpotEvalConfig())
    predictions_answer = {"a": "no", "b": "science fiction"}
    predictions_sp = {
        "a": [["Scott Derrickson", 0], ["Ed Wood", 0]],
        "b": [["The Matrix", 0]],
    }
    gold_items = [
        HotpotItem(
            _id="a", question="?", answer="no",
            supporting_facts=[["Scott Derrickson", 0], ["Ed Wood", 0]],
            context=[], type="comparison", level="hard",
        ),
        HotpotItem(
            _id="b", question="?", answer="science fiction",
            supporting_facts=[["The Matrix", 0]],
            context=[], type="bridge", level="hard",
        ),
    ]
    metrics = runner._compute_metrics(
        predictions_answer, predictions_sp, gold_items
    )
    assert metrics["em"] == 1.0
    assert metrics["f1"] == 1.0
    assert metrics["sp_em"] == 1.0
    assert metrics["sp_f1"] == 1.0
    assert metrics["joint_em"] == 1.0
    assert metrics["joint_f1"] == 1.0


def test_compute_metrics_sp_idx_type_matches():
    """预测端 int 下标必须能与 gold 的 int 下标匹配（回归 B：str '0' vs int 0）。"""
    runner = HotpotEvalRunner(HotpotEvalConfig())
    # answer 故意错，只看 sp：预测命中两个 title、下标 0
    predictions_answer = {"x": ""}
    predictions_sp = {"x": [["T1", 0], ["T2", 0]]}
    gold_items = [
        HotpotItem(
            _id="x", question="?", answer="whatever",
            supporting_facts=[["T1", 0], ["T2", 0]],
            context=[], type="comparison", level="hard",
        ),
    ]
    metrics = runner._compute_metrics(
        predictions_answer, predictions_sp, gold_items
    )
    assert metrics["sp_em"] == 1.0
    assert metrics["sp_f1"] == 1.0
