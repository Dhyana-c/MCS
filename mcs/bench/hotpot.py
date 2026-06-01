"""HotpotQA 多跳问答端到端评测框架。

从 HotpotQA 数据加载 → MCS ingest → MCS query → 预测格式转换 → 官方指标计算，
一条命令跑通完整评测流程。
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 实测 token 模型（来自真账单反推，与 multihop 口径一致）：约 9K token/段
# （7.5K input + 1.5K output），每条 HotpotQA ~10 段 ingest + 1 次 query ≈ 90K token/条。
# 替换旧的 ~7900/条估算。
_TOKENS_IN_PER_CHUNK = 7500
_TOKENS_OUT_PER_CHUNK = 1500
_CHUNKS_PER_ITEM = 10
_QUERY_TOKENS_IN = 800
_QUERY_TOKENS_OUT = 100


def _ensure_utf8_stdout() -> None:
    """让 stdout 以 UTF-8 + errors='replace' 输出。

    Windows 控制台/重定向默认 GBK，预测里可能出现非 GBK 字符（如 č），
    直接 print 会抛 UnicodeEncodeError 并中断整次评测。
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ─── 2. 数据加载 ───────────────────────────────────────────────────────────────


@dataclass
class HotpotItem:
    """一条 HotpotQA 数据。"""

    _id: str
    question: str
    answer: str
    supporting_facts: list[list[str]]  # [[title, sent_idx_str], ...]
    context: list[list[Any]]  # [[title, [s1, s2, ...]], ...]
    type: str  # "bridge" | "comparison"
    level: str  # dev 全为 "hard"


class HotpotDataLoader:
    """加载 HotpotQA JSON 数据，支持按 type 分层采样。"""

    def __init__(
        self,
        path: str,
        subset: int | None = None,
        sample_strategy: str = "uniform",
        seed: int = 42,
    ):
        self.path = path
        self.subset = subset
        self.sample_strategy = sample_strategy
        self.seed = seed

    def load(self) -> list[HotpotItem]:
        with open(self.path, encoding="utf-8") as f:
            raw = json.load(f)
        items = [self._parse(r) for r in raw]
        if self.subset is None:
            return items
        return self._sample(items, self.subset, self.sample_strategy)

    @staticmethod
    def _parse(raw: dict) -> HotpotItem:
        return HotpotItem(
            _id=raw["_id"],
            question=raw["question"],
            answer=raw["answer"],
            supporting_facts=raw["supporting_facts"],
            context=raw["context"],
            type=raw["type"],
            level=raw["level"],
        )

    def _sample(
        self, items: list[HotpotItem], n: int, strategy: str
    ) -> list[HotpotItem]:
        rng = random.Random(self.seed)
        by_type: dict[str, list[HotpotItem]] = {}
        for item in items:
            by_type.setdefault(item.type, []).append(item)

        if strategy == "proportional":
            total = len(items)
            picked: list[HotpotItem] = []
            for t, group in by_type.items():
                k = max(1, round(n * len(group) / total))
                k = min(k, len(group))
                picked.extend(rng.sample(group, k))
            if len(picked) > n:
                picked = rng.sample(picked, n)
            return picked

        # uniform: 每个 type 平均分配
        n_types = len(by_type)
        per_type = max(1, n // n_types)
        picked = []
        for t, group in by_type.items():
            k = min(per_type, len(group))
            picked.extend(rng.sample(group, k))
        # 补足差额
        remaining = n - len(picked)
        if remaining > 0:
            seen_ids = {it._id for it in picked}
            pool = [it for it in items if it._id not in seen_ids]
            if pool:
                picked.extend(rng.sample(pool, min(remaining, len(pool))))
        return picked


# ─── 3. Ingest 适配 ───────────────────────────────────────────────────────────


def format_context_paragraph(title: str, sentences: list[str]) -> str:
    """将 `[title, [s1, s2, ...]]` 格式化为 `"{title}: {s1}. {s2}."` 。"""
    body = " ".join(sentences)
    return f"{title}: {body}"


def ingest_hotpot_item(item: HotpotItem, llm: str = "deepseek") -> Any:
    """为一条 HotpotItem 创建独立 MCS 实例并摄入 context 中的所有段落。

    返回已初始化的 MCS 实例（图已构建完毕）。
    """
    from mcs import MCS, MCSConfig

    config = MCSConfig.knowledge_graph(llm=llm)
    # 覆盖存储为 :memory:，保证图隔离（D3）
    config.plugin_configs["sqlite_storage"] = {"path": ":memory:"}
    # 从环境变量读取 API key
    if llm == "deepseek":
        import os

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        config.plugin_configs["deepseek_llm"]["api_key"] = api_key
    elif llm == "claude":
        import os

        auth_token = os.environ.get("ANTHROPIC_API_KEY", "")
        config.plugin_configs["claude_llm"]["auth_token"] = auth_token
    elif llm == "ollama":
        import os

        config.plugin_configs["ollama_llm"].update({
            "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            "model": os.environ.get("OLLAMA_MODEL", ""),
        })

    mcs = MCS(config)
    mcs.initialize()

    for idx, (title, sentences) in enumerate(item.context):
        text = format_context_paragraph(title, sentences)
        try:
            mcs.ingest(
                text,
                doc_id=item._id,
                chunk_id=str(idx),
                section_title=title,
            )
        except Exception:
            # 单段摄入失败不应丢掉整条数据（已成功的段落仍保留在图里）
            logger.warning(
                "ingest failed for %s paragraph %d (%r); skipping",
                item._id, idx, title,
            )

    return mcs


# ─── 4. Query 适配 ────────────────────────────────────────────────────────────


# 仅当问题以这些系动词/助动词开头时，才把它当作 yes/no 句式
_YESNO_QUESTION_PREFIXES = {
    "is", "are", "was", "were", "do", "does", "did",
    "has", "have", "had", "can", "could", "would", "will", "should",
}


def _extract_yes_no(nodes: list[Any]) -> str | None:
    """从节点内容中判断 yes/no 答案。"""
    affirmative = {"yes", "true", "correct", "affirmative"}
    negative = {"no", "false", "incorrect", "negative"}

    for node in nodes:
        content_lower = node.content.lower()
        name_lower = node.name.lower()
        for text in (name_lower, content_lower):
            words = set(text.split())
            if words & affirmative and not (words & negative):
                return "yes"
            if words & negative and not (words & affirmative):
                return "no"
    return None


def extract_answer(nodes: list[Any], question: str = "") -> str:
    """从 query 返回的 List[Node] 中提取答案字符串。"""
    if not nodes:
        return ""

    # 仅当问题是 yes/no 句式（以系动词/助动词开头）时才尝试 yes/no，
    # 否则节点内容里常见的 "no"/"yes" 等词会污染实体题的答案。
    tokens = question.strip().lower().split()
    first = tokens[0] if tokens else ""
    if first in _YESNO_QUESTION_PREFIXES:
        yn = _extract_yes_no(nodes)
        if yn is not None:
            return yn

    # 实体答案：取 rank 最高的节点 name
    return nodes[0].name


def extract_supporting_facts(
    nodes: list[Any], top_n: int | None = 2
) -> list[list[str]]:
    """从返回节点提取 supporting facts，按 node rank 取 **top-N** 去重 title。

    从 source_tracking 的 section_title 取 title，sent_idx 统一取 0（D8 下界）。
    HotpotQA gold sp 通常恰为 2 篇支撑文档，而 MCS 易把所有来源 title 全吐出
    （过度预测，拉低 sp 精确率/sp_em）。按 rank 取 top-N 剪枝缓解之；
    ``top_n=None`` 表示不剪枝（保留旧行为：吐出全部去重 title）。
    """
    titles: list[str] = []
    seen: set[str] = set()
    for node in nodes:
        sources = (
            (node.extensions or {})
            .get("source_tracking", {})
            .get("sources", [])
        )
        for src in sources:
            title = src.section_title if hasattr(src, "section_title") else src.get("section_title")
            if title and title not in seen:
                seen.add(title)
                titles.append(title)
                if top_n is not None and len(titles) >= top_n:
                    # sent_idx 必须是 int 0（与 gold 的 int 下标一致，否则元组永不匹配）
                    return [[t, 0] for t in titles]
    return [[t, 0] for t in titles]


def extract_prediction(
    nodes: list[Any],
    item_id: str,
    question: str = "",
    sp_top_n: int | None = 2,
) -> dict:
    """整合 answer + supporting_facts 提取，返回预测字典。"""
    answer = extract_answer(nodes, question)
    sp = extract_supporting_facts(nodes, top_n=sp_top_n)
    return {"_id": item_id, "answer": answer, "sp": sp}


# ─── 5. 评测运行器 ────────────────────────────────────────────────────────────


@dataclass
class HotpotEvalConfig:
    """评测配置。"""

    data_path: str = r"D:\code\hotpot\hotpot_dev_distractor_v1.json"
    eval_script_dir: str = r"D:\code\hotpot"
    subset: int | None = 100
    sample_strategy: str = "uniform"
    llm_backend: str = "deepseek"
    output_dir: str = "./bench_output"
    dry_run: bool = False
    resume: bool = True
    seed: int = 42
    sp_top_n: int | None = 2  # supporting-facts 按 rank 取 top-N 剪枝；None=不剪枝


class HotpotEvalRunner:
    """HotpotQA 评测运行器。"""

    def __init__(self, config: HotpotEvalConfig | None = None):
        self.config = config or HotpotEvalConfig()

    def run(self) -> dict[str, float]:
        """加载 → 逐条 ingest+query → 收集预测 → 计算指标。"""
        _ensure_utf8_stdout()
        cfg = self.config
        output_dir = Path(cfg.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 加载数据
        loader = HotpotDataLoader(
            cfg.data_path,
            subset=cfg.subset,
            sample_strategy=cfg.sample_strategy,
            seed=cfg.seed,
        )
        items = loader.load()
        total = len(items)

        pred_file = output_dir / "predictions.json"
        progress_path = output_dir / "progress.json"

        # 断点续跑：复用已落盘的预测（含 answer/sp），保证恢复后指标完整
        predictions_answer: dict[str, str] = {}
        predictions_sp: dict[str, list[list[Any]]] = {}
        if cfg.resume and pred_file.exists():
            try:
                saved = json.loads(pred_file.read_text(encoding="utf-8"))
                predictions_answer = dict(saved.get("answer", {}))
                predictions_sp = dict(saved.get("sp", {}))
            except Exception:
                logger.warning("无法读取已有 predictions.json，从头开始")
        done_ids = set(predictions_answer)
        if done_ids:
            logger.info("Resume: skipping %d completed items", len(done_ids))

        def _persist() -> None:
            pred_file.write_text(
                json.dumps(
                    {"answer": predictions_answer, "sp": predictions_sp},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            progress_path.write_text(
                json.dumps(sorted(done_ids)), encoding="utf-8"
            )

        for i, item in enumerate(items, 1):
            if item._id in done_ids:
                continue

            # ingest + query：任何一步失败都记为空预测（仍计入分母，避免漏题抬高指标）
            nodes: list[Any] = []
            mcs = None
            try:
                mcs = ingest_hotpot_item(item, llm=cfg.llm_backend)
                result = mcs.query(item.question)
                nodes = result if isinstance(result, list) else []
            except Exception:
                logger.exception("Item failed: %s", item._id)
                nodes = []
            finally:
                if mcs is not None:
                    mcs.shutdown()

            # extract prediction
            pred = extract_prediction(
                nodes, item._id, item.question, sp_top_n=cfg.sp_top_n
            )
            predictions_answer[item._id] = pred["answer"]
            predictions_sp[item._id] = pred["sp"]
            done_ids.add(item._id)

            # 进度输出（stdout 已切 UTF-8，非 GBK 字符不会中断评测）
            print(
                f"[{i}/{total}] {item._id} | "
                f"answer={pred['answer']!r} | sp_titles={[t[0] for t in pred['sp']]}"
            )

            # 每条都增量落盘预测与进度，崩溃也不丢已完成的工作
            _persist()

        # 导出子集 gold 文件
        gold_items = [it for it in items if it._id in predictions_answer]
        gold_file = output_dir / "gold_subset.json"
        gold_file.write_text(
            json.dumps([asdict(it) for it in gold_items], ensure_ascii=False),
            encoding="utf-8",
        )

        # 计算指标
        metrics = self._compute_metrics(predictions_answer, predictions_sp, gold_items)
        self._print_metrics(metrics)

        # 写出指标
        metrics_file = output_dir / "metrics.json"
        metrics_file.write_text(
            json.dumps(metrics, indent=2), encoding="utf-8"
        )

        return metrics

    def _compute_metrics(
        self,
        predictions_answer: dict[str, str],
        predictions_sp: dict[str, list[list[Any]]],
        gold_items: list[HotpotItem],
    ) -> dict[str, float]:
        """复用 hotpot_evaluate_v1 的 update_answer/update_sp，按官方口径逐条聚合。

        官方 joint 是"每条的 answer/sp prec、recall 相乘后再算 F1，em 相乘"再求平均，
        不是对平均值取 min。这里完整复刻 eval() 的聚合循环并返回指标字典
        （eval() 本身只 print 不 return，故不直接调用它）。
        """
        n = len(gold_items)
        if n == 0:
            return {"em": 0.0, "f1": 0.0, "sp_em": 0.0, "sp_f1": 0.0,
                    "joint_em": 0.0, "joint_f1": 0.0}

        try:
            if self.config.eval_script_dir not in sys.path:
                sys.path.insert(0, self.config.eval_script_dir)
            from hotpot_evaluate_v1 import update_answer, update_sp
        except ImportError:
            logger.warning(
                "无法导入 hotpot_evaluate_v1（缺 ujson？），改用内置 fallback 指标"
            )
            return self._fallback_metrics(
                predictions_answer, predictions_sp, gold_items
            )

        # 官方函数会读写以下 12 个键，必须全部初始化
        metrics = {
            "em": 0.0, "f1": 0.0, "prec": 0.0, "recall": 0.0,
            "sp_em": 0.0, "sp_f1": 0.0, "sp_prec": 0.0, "sp_recall": 0.0,
            "joint_em": 0.0, "joint_f1": 0.0, "joint_prec": 0.0, "joint_recall": 0.0,
        }
        for item in gold_items:
            pred_ans = predictions_answer.get(item._id, "")
            em, prec, recall = update_answer(metrics, pred_ans, item.answer)

            pred_sp = predictions_sp.get(item._id, [])
            # gold 下标归一为 int，和预测端的 int 0 对齐
            gold_sp = [[t, int(idx)] for t, idx in item.supporting_facts]
            sp_em, sp_prec, sp_recall = update_sp(metrics, pred_sp, gold_sp)

            joint_prec = prec * sp_prec
            joint_recall = recall * sp_recall
            if joint_prec + joint_recall > 0:
                joint_f1 = 2 * joint_prec * joint_recall / (joint_prec + joint_recall)
            else:
                joint_f1 = 0.0
            metrics["joint_em"] += em * sp_em
            metrics["joint_f1"] += joint_f1
            metrics["joint_prec"] += joint_prec
            metrics["joint_recall"] += joint_recall

        for k in metrics:
            metrics[k] /= n

        return {
            "em": metrics["em"], "f1": metrics["f1"],
            "sp_em": metrics["sp_em"], "sp_f1": metrics["sp_f1"],
            "joint_em": metrics["joint_em"], "joint_f1": metrics["joint_f1"],
        }

    @staticmethod
    def _fallback_metrics(
        predictions_answer: dict[str, str],
        predictions_sp: dict[str, list[list[Any]]],
        gold_items: list[HotpotItem],
    ) -> dict[str, float]:
        """内置近似指标（仅当 hotpot_evaluate_v1 不可用时）。

        sp 仅按 title 比较（无句子级），joint 按官方口径"每条乘积再平均"。
        与官方仍有差异（无 article/标点归一、sp 无句子下标），正式结果请用官方路径。
        """
        n = len(gold_items)
        if n == 0:
            return {"em": 0.0, "f1": 0.0, "sp_em": 0.0, "sp_f1": 0.0,
                    "joint_em": 0.0, "joint_f1": 0.0}

        em_sum = f1_sum = sp_em_sum = sp_f1_sum = 0.0
        joint_em_sum = joint_f1_sum = 0.0
        for item in gold_items:
            pred = predictions_answer.get(item._id, "").strip().lower()
            gold = item.answer.strip().lower()
            em_i = 1.0 if pred == gold else 0.0
            pred_tokens = set(pred.split())
            gold_tokens = set(gold.split())
            common = pred_tokens & gold_tokens
            f1_i = 0.0
            if pred_tokens and gold_tokens and common:
                p = len(common) / len(pred_tokens)
                r = len(common) / len(gold_tokens)
                f1_i = 2 * p * r / (p + r) if (p + r) else 0.0

            pred_titles = {t for t, _ in predictions_sp.get(item._id, [])}
            gold_titles = {t for t, _ in item.supporting_facts}
            sp_em_i = 1.0 if pred_titles == gold_titles else 0.0
            sp_common = pred_titles & gold_titles
            sp_f1_i = 0.0
            if pred_titles and gold_titles and sp_common:
                p = len(sp_common) / len(pred_titles)
                r = len(sp_common) / len(gold_titles)
                sp_f1_i = 2 * p * r / (p + r) if (p + r) else 0.0

            em_sum += em_i
            f1_sum += f1_i
            sp_em_sum += sp_em_i
            sp_f1_sum += sp_f1_i
            joint_em_sum += em_i * sp_em_i
            joint_f1_sum += f1_i * sp_f1_i

        return {
            "em": em_sum / n,
            "f1": f1_sum / n,
            "sp_em": sp_em_sum / n,
            "sp_f1": sp_f1_sum / n,
            "joint_em": joint_em_sum / n,
            "joint_f1": joint_f1_sum / n,
        }

    @staticmethod
    def _print_metrics(metrics: dict[str, float]) -> None:
        print("\n=== HotpotQA Evaluation Results ===")
        for k, v in metrics.items():
            print(f"  {k}: {v:.4f}")

    def dry_run(self) -> dict[str, Any]:
        """仅统计预估 token 消耗，不执行 LLM 调用。"""
        cfg = self.config
        loader = HotpotDataLoader(
            cfg.data_path,
            subset=cfg.subset,
            sample_strategy=cfg.sample_strategy,
            seed=cfg.seed,
        )
        items = loader.load()
        n = len(items)

        # 实测 token 模型（~90K/条）：每条 ~10 段 ingest（每段 7.5K in + 1.5K out）+ 1 次 query。
        input_tokens = n * (_CHUNKS_PER_ITEM * _TOKENS_IN_PER_CHUNK + _QUERY_TOKENS_IN)
        output_tokens = n * (_CHUNKS_PER_ITEM * _TOKENS_OUT_PER_CHUNK + _QUERY_TOKENS_OUT)
        total_tokens = input_tokens + output_tokens

        # 费用估算
        prices = {
            "deepseek": {"input": 0.14 / 1_000_000, "output": 0.28 / 1_000_000},
            "claude": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
        }
        price = prices.get(cfg.llm_backend, prices["deepseek"])
        cost = input_tokens * price["input"] + output_tokens * price["output"]

        estimate = {
            "n_items": n,
            "total_tokens_estimated": total_tokens,
            "input_tokens_estimated": input_tokens,
            "output_tokens_estimated": output_tokens,
            "estimated_cost_usd": round(cost, 4),
            "llm_backend": cfg.llm_backend,
        }
        print("\n=== Dry Run Estimate ===")
        for k, v in estimate.items():
            print(f"  {k}: {v}")
        return estimate


# ─── 6. CLI 入口 ──────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MCS HotpotQA Evaluation Benchmark"
    )
    parser.add_argument(
        "--subset",
        type=int,
        default=100,
        help="Number of items to evaluate (0 for full set)",
    )
    parser.add_argument(
        "--llm",
        choices=["deepseek", "claude", "ollama"],
        default="deepseek",
        help="LLM backend to use",
    )
    parser.add_argument(
        "--output",
        default="./bench_output",
        help="Output directory for results",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only estimate token usage, no LLM calls",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Start from scratch, ignoring progress file",
    )
    parser.add_argument(
        "--strategy",
        choices=["uniform", "proportional"],
        default="uniform",
        help="Sampling strategy",
    )
    parser.add_argument(
        "--data-path",
        default=r"D:\code\hotpot\hotpot_dev_distractor_v1.json",
        help="Path to HotpotQA JSON data file",
    )
    parser.add_argument(
        "--eval-script-dir",
        default=r"D:\code\hotpot",
        help="Directory containing hotpot_evaluate_v1.py",
    )
    parser.add_argument(
        "--sp-top-n",
        type=int,
        default=2,
        help="Supporting-facts top-N pruning by node rank (0 = no pruning)",
    )

    args = parser.parse_args()

    config = HotpotEvalConfig(
        data_path=args.data_path,
        eval_script_dir=args.eval_script_dir,
        subset=args.subset if args.subset > 0 else None,
        sample_strategy=args.strategy,
        llm_backend=args.llm,
        output_dir=args.output,
        dry_run=args.dry_run,
        resume=not args.no_resume,
        sp_top_n=args.sp_top_n if args.sp_top_n > 0 else None,
    )

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    runner = HotpotEvalRunner(config)
    if config.dry_run:
        runner.dry_run()
    else:
        runner.run()


if __name__ == "__main__":
    main()
