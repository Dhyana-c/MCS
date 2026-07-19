"""LoCoMo 评测指标（D5/D7/D9）。

**口径分离**（spec 要求）：主表仅 LLM-judge 正确率（对齐 Mem0/Zep 口径）；F1 / 时间容忍
/ 检索 Recall 为**副指标**单列，MUST NOT 与 judge 数字混入同一对比表。

- **QA 轨主指标 = LLM-judge 正确率**（5 类分项）：``judge_correct`` 调 LLM 判 agent 答案
  与 gold 语义等价。adversarial（cat 5）弃答判定交 judge（正确 = 表达"该信息未被提及"，
  答出具体内容尤其 ``adversarial_answer`` = 错误），**不用关键词匹配**（D7）。
- **副指标**：F1（token-level + 轻 stemming，对齐 LoCoMo 论文口径）、时间偏移容忍
  （temporal 类单列）、rubric（open-domain，预留）。
- **检索轨**（移植 evidence 的题）：session 级 Recall@k（any / all-evidence hit，k=5/10/20），
  **仅诊断用**（Multi-Mention Flaw 致系统偏低，MUST NOT 与外部系统对比）。

judge 是 LLM 调用；纯函数（recall/F1/时间容忍）单测不走 LLM，judge 单测 patch
``_call_judge_llm``。
"""

from __future__ import annotations

import json
import os
import re
import statistics
from collections import Counter
from typing import Any, Callable

from bench.locomo.data import CATEGORY_NAMES, dia_id_to_session

# 检索轨 Recall@k 的默认 k 值（session 级）。
DEFAULT_K_VALUES: tuple[int, ...] = (5, 10, 20)
# temporal 副指标：预测年份与 gold 差 <= 此值视为对（日级偏移不在此副指标，年级）。
TEMPORAL_MAX_OFFSET = 1


# ---------------------------------------------------------------------------
# 检索轨：session 级 Recall@k（纯函数）
# ---------------------------------------------------------------------------


def chunk_id_to_session(chunk_id: str) -> int | None:
    """``"session_3"`` -> ``3``；不合规返 ``None``。"""
    m = re.fullmatch(r"session_(\d+)", chunk_id)
    return int(m.group(1)) if m else None


def evidence_to_sessions(evidence: list[str]) -> set[int]:
    """gold session 集合（evidence dia_id 的 ``D{N}`` 前缀去重）。"""
    out: set[int] = set()
    for d in evidence:
        n = dia_id_to_session(d)
        if n is not None:
            out.add(n)
    return out


def retrieved_sessions(nodes: list[Any]) -> list[int]:
    """query() 返回的节点（按 rank）-> 按 rank 去重的 session 序列。

    读每个节点 ``extensions.source_tracking.sources[].chunk_id``（session 级溯源——
    LoCoMo 每 doc 的 ``doc_id`` 恒定，区分靠 ``chunk_id=session_N``）。一个节点可能
    来自多 session（merge 后）→ 取其来源并集。
    """
    seen: set[int] = set()
    ranked: list[int] = []
    for node in nodes:
        sources = (
            (getattr(node, "extensions", {}) or {})
            .get("source_tracking", {})
            .get("sources", [])
        )
        for s in sources:
            cid = s.chunk_id if hasattr(s, "chunk_id") else (
                s.get("chunk_id") if isinstance(s, dict) else None
            )
            if cid:
                n = chunk_id_to_session(cid)
                if n is not None and n not in seen:
                    seen.add(n)
                    ranked.append(n)
    return ranked


def session_recall_at_k(ranked: list[int], gold: set[int], k: int) -> float:
    """top-k 命中的 gold session 占比。"""
    if not gold:
        return 0.0
    return len(set(ranked[:k]) & gold) / len(gold)


def any_evidence_hit(ranked: list[int], gold: set[int], k: int) -> bool:
    """top-k 是否命中**至少一个** gold session（主检索指标）。"""
    if not gold:
        return False
    return bool(set(ranked[:k]) & gold)


def all_evidence_hit(ranked: list[int], gold: set[int], k: int) -> bool:
    """top-k 是否命中**全部** gold session（副检索指标）。"""
    if not gold:
        return False
    return gold <= set(ranked[:k])


# ---------------------------------------------------------------------------
# QA 轨副指标：F1（token-level + stemming）/ 时间偏移容忍（纯函数）
# ---------------------------------------------------------------------------


_ARTICLES = re.compile(r"\b(a|an|the)\b", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")


def _normalize_tokens(text: str) -> list[str]:
    """SQuAD 式归一化：lower、去冠词、去标点、按空白切。"""
    if not text:
        return []
    s = _ARTICLES.sub(" ", text.lower())
    s = _NON_ALNUM.sub(" ", s)
    return [w for w in s.split() if w]


def _light_stem(word: str) -> str:
    """轻 stemming：剥常见英文后缀（-ing/-ed/-es/-s），词干太短不动。"""
    for suf in ("ing", "ed", "es", "s"):
        if len(word) > len(suf) + 2 and word.endswith(suf):
            return word[: -len(suf)]
    return word


def f1_token_level(pred: str | None, gold: str | None) -> float:
    """token-level F1（归一化 + 轻 stemming，对齐 LoCoMo 论文副口径）。"""
    if not pred or not gold:
        return 0.0
    p = [_light_stem(w) for w in _normalize_tokens(pred)]
    g = [_light_stem(w) for w in _normalize_tokens(gold)]
    if not p or not g:
        return 0.0
    common = Counter(p) & Counter(g)
    nc = sum(common.values())
    if nc == 0:
        return 0.0
    precision = nc / len(p)
    recall = nc / len(g)
    return 2 * precision * recall / (precision + recall)


def _extract_year(text: str | None) -> int | None:
    if not text:
        return None
    m = _YEAR_RE.search(text)
    return int(m.group(1)) if m else None


def temporal_offset_accept(
    pred: str | None, gold: str | None, max_offset: int = TEMPORAL_MAX_OFFSET
) -> bool:
    """temporal 副指标：预测与 gold 的年份差 <= ``max_offset`` 视为对（年级容忍）。

    仅认 ``19xx``/``20xx`` 四位年；无年的 temporal 答案返 ``False``（不计入此副指标分母
    更合适，但这里保守返 False，由 aggregate 仅对 cat-2 汇总）。
    """
    py = _extract_year(pred)
    gy = _extract_year(gold)
    if py is None or gy is None:
        return False
    return abs(py - gy) <= max_offset


# ---------------------------------------------------------------------------
# QA 轨主指标：LLM-judge
# ---------------------------------------------------------------------------


JUDGE_SYSTEM_PROMPT = (
    "# 角色\n"
    "你是答案评判员，判断 agent 的回答是否与标准答案（gold）语义等价。\n\n"
    "# 判定规则\n"
    "- **非 adversarial 类（category 1-4）**：agent 答案与 gold 语义等价即判 correct=true；"
    "不要求字面一致、不要求完整句子，关键信息一致即可。agent 答错 / 漏关键信息 / 臆测 = false。\n"
    "- **adversarial 类（category 5）**：正确答案 = 该信息在对话中**未被提及**。agent 正确表现 = "
    "明确表达「该信息未被提及 / 我不知道 / 对话里没说」（弃答）→ correct=true；agent 答出具体内容"
    "（尤其接近 adversarial_answer 的陷阱）= correct=false。\n\n"
    '# 输出\n'
    '严格输出 JSON：{"correct": true|false, "reason": "一句话理由"}。只返回 JSON，不要其他文字。'
)


def _parse_verdict(raw: Any) -> dict:
    """从 llm_call 返回解析 {correct, reason}；容错（抽取首个 JSON 对象）。"""
    if isinstance(raw, dict):
        content = raw.get("content", raw)
    else:
        content = raw
    if not isinstance(content, str):
        return {"correct": False, "reason": "judge 返回非文本"}
    m = re.search(r"\{[^{}]*\}", content, re.DOTALL)
    if not m:
        return {"correct": False, "reason": f"judge 返回无 JSON：{content[:120]}"}
    try:
        v = json.loads(m.group(0))
        return {"correct": bool(v.get("correct", False)),
                "reason": str(v.get("reason", ""))}
    except json.JSONDecodeError:
        return {"correct": False, "reason": f"judge JSON 解析失败：{m.group(0)[:120]}"}


def _default_judge_llm() -> Callable[[list[dict], list[dict]], Any]:
    """从 DEEPSEEK_* env 构造 judge LLM callable（与 golden_cage 同口径）。"""
    from mcs_agent.llm import make_openai_llm_call
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY 未设置（judge 需 LLM，检查 .env）")
    return make_openai_llm_call(
        os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key,
        os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


def _call_judge_llm(
    question: str,
    reply: str,
    category: int,
    gold_answer: str | None,
    adversarial_answer: str | None,
    llm_call: Callable[[list[dict], list[dict]], Any] | None,
) -> dict:
    """调 LLM judge 并解析裁决（单测 patch 此函数绕过真实 LLM）。"""
    if llm_call is None:
        llm_call = _default_judge_llm()
    payload = {
        "category": category,
        "category_name": CATEGORY_NAMES.get(category, f"cat-{category}"),
        "question": question,
        "gold_answer": gold_answer,
        "adversarial_answer": adversarial_answer,
        "agent_reply": reply,
    }
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    raw = llm_call(messages, [])  # tools=[] -> OpenAIAgentLLM 自动省略 tools=（deepseek 400 规避）
    return _parse_verdict(raw)


def judge_correct(
    question: str,
    reply: str,
    category: int,
    *,
    gold_answer: str | None = None,
    adversarial_answer: str | None = None,
    llm_call: Callable[[list[dict], list[dict]], Any] | None = None,
) -> bool:
    """LLM-judge 主指标：判 agent 答案是否正确（adversarial 走弃答判定）。"""
    return _call_judge_llm(
        question, reply, category, gold_answer, adversarial_answer, llm_call
    )["correct"]


# ---------------------------------------------------------------------------
# 聚合（口径分离：主表 judge / 副表 f1·temporal·retrieval）
# ---------------------------------------------------------------------------


def _mean(xs: list[float]) -> float:
    return statistics.fmean(xs) if xs else 0.0


def _bool_mean(xs: list[bool]) -> float:
    return _mean([1.0 if x else 0.0 for x in xs])


def aggregate_qa(qa_results: list[dict]) -> dict:
    """聚合 QA 轨：主表 judge 正确率 + 副表 F1 / temporal（按类别 + overall）。

    ``qa_results`` 每条含 ``category``、``judge_correct``（bool）、``f1``（float，可选）、
    ``temporal_accept``（bool，可选，仅 cat-2）。返回结构**显式分离口径**：
    ``judge`` 为主表，``f1`` / ``temporal_offset`` 为副表。
    """
    by_cat: dict[int, list[dict]] = {}
    for r in qa_results:
        by_cat.setdefault(int(r["category"]), []).append(r)

    judge: dict[str, dict] = {}
    f1: dict[str, dict] = {}
    for cat in sorted(by_cat):
        rs = by_cat[cat]
        name = f"cat_{cat}_{CATEGORY_NAMES.get(cat, '')}".rstrip("_")
        judge[name] = {"n": len(rs),
                       "accuracy": _bool_mean([bool(r.get("judge_correct")) for r in rs])}
        f1[name] = {"n": len(rs),
                    "mean": _mean([float(r.get("f1", 0.0)) for r in rs])}
    all_rs = list(qa_results)
    judge["overall"] = {"n": len(all_rs),
                        "accuracy": _bool_mean([bool(r.get("judge_correct")) for r in all_rs])}
    f1["overall"] = {"n": len(all_rs),
                     "mean": _mean([float(r.get("f1", 0.0)) for r in all_rs])}

    out: dict[str, Any] = {"judge": judge, "f1": f1}
    # temporal 副指标仅 cat-2
    temp = [r for r in by_cat.get(2, []) if "temporal_accept" in r]
    if temp:
        out["temporal_offset"] = {
            "n": len(temp),
            "accept_rate": _bool_mean([bool(r["temporal_accept"]) for r in temp]),
        }
    return out


def aggregate_retrieval(
    retrieval_results: list[dict], k_values: tuple[int, ...] = DEFAULT_K_VALUES
) -> dict:
    """聚合检索轨：session 级 Recall@k + any / all-evidence hit（**诊断性副指标**）。

    ``retrieval_results`` 每条含 ``gold_sessions``（list[int]）与 ``ranked_sessions``
    （list[int]）。MUST NOT 与外部系统对比（Multi-Mention Flaw 致系统偏低）。
    """
    rec: dict[str, Any] = {"n": len(retrieval_results)}
    for k in k_values:
        recalls: list[float] = []
        any_hits: list[float] = []
        all_hits: list[float] = []
        for r in retrieval_results:
            gold = set(r.get("gold_sessions") or [])
            ranked = list(r.get("ranked_sessions") or [])
            if not gold:
                continue
            recalls.append(session_recall_at_k(ranked, gold, k))
            any_hits.append(1.0 if any_evidence_hit(ranked, gold, k) else 0.0)
            all_hits.append(1.0 if all_evidence_hit(ranked, gold, k) else 0.0)
        rec[f"recall@{k}"] = _mean(recalls)
        rec[f"any_hit@{k}"] = _mean(any_hits)
        rec[f"all_hit@{k}"] = _mean(all_hits)
    return rec


def aggregate_locomo_metrics(
    qa_results: list[dict],
    retrieval_results: list[dict] | None = None,
    *,
    k_values: tuple[int, ...] = DEFAULT_K_VALUES,
) -> dict:
    """汇总 QA + 检索双轨。返回 ``{"qa": ..., "retrieval": ...}``（口径分离）。"""
    out: dict[str, Any] = {"qa": aggregate_qa(qa_results)}
    if retrieval_results:
        out["retrieval"] = aggregate_retrieval(retrieval_results, k_values)
    return out
