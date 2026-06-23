"""闭卷泄漏探针：15 个 fully-missed 问题，不给图/不给检索，纯让 deepseek-chat 凭
预训练知识答，量化 MultiHop-RAG 语料对 deepseek 的泄漏。

判读口径：
- **实体题**（gold=具体实体名，如 Alameda Research / Tyreek Hill / Everton FC）：闭卷答对
  = 强泄漏信号，正是 agent「实体推断」捷径的来源。
- **yes/no 题**：50% 基线，单题对错弱证据，看整体偏离。

prompt 明确「不确定就说 UNKNOWN、不要猜」，把"真知道"和"瞎蒙"尽量分开。
判分为启发式（归一 + 包含匹配），全部打印原文供人工核对（仅 15 条）。

用法:
  .venv/Scripts/python.exe bench/multihop_rag/scripts/closed_book_probe.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import os  # noqa: E402

from openai import OpenAI  # noqa: E402

from bench._env import load_dotenv  # noqa: E402

_BENCH = _ROOT / "bench" / "multihop_rag"
MISSED = _BENCH / "outputs" / "dschat_full_16k_bfsroot_newprompt" / "results.jsonl"
QA = _BENCH / "data" / "multihoprag_qa.json"
OUT = _BENCH / "outputs" / "agent_case_study" / "closed_book_probe.json"

# gold answer 是具体实体名的题（强泄漏信号）；其余按 yes/no 基线读
ENTITY_QIDS = {"6aa1c570910a", "3d1803a7e9ed", "ed2bb96d847b", "9989e069264c", "240b7c0abe1f"}

SYSTEM = (
    "You answer strictly from your own pretrained knowledge. You have NO access to "
    "any documents, database, or retrieval. Answer the question as concisely as "
    "possible (a name, an entity, or yes/no). If you genuinely do not know the "
    "specific answer, reply exactly UNKNOWN — do NOT guess."
)


def load_cases() -> list[dict]:
    qa = {hashlib.md5(q["query"].encode("utf-8")).hexdigest()[:12]: q
          for q in json.load(QA.open(encoding="utf-8"))}
    res = [json.loads(l) for l in MISSED.read_text(encoding="utf-8").splitlines() if l.strip()]
    missed = [r for r in res if not (set(r["gold"]) & set(r["ranked"]))]
    out = []
    for r in missed:
        q = qa[r["query_id"]]
        out.append({"qid": r["query_id"], "type": r["type"],
                    "question": q["query"], "gold_answer": q.get("answer", "")})
    return out


def _norm(s: str) -> str:
    return "".join(c.lower() for c in s if c.isalnum() or c.isspace()).strip()


def judge(gold: str, ans: str) -> str:
    """启发式判分：correct / wrong / unknown。yes/no 与实体分别处理。"""
    g, a = _norm(gold), _norm(ans)
    if not a or "unknown" in a:
        return "unknown"
    yesset = {"yes", "agree", "both", "true"}
    noset = {"no", "disagree", "false"}
    if g in yesset or g in noset:
        first = a.split()[0] if a.split() else ""
        a_yes = any(w in a.split()[:4] for w in yesset)
        a_no = any(w in a.split()[:4] for w in noset)
        if g in yesset and a_yes and not a_no:
            return "correct"
        if g in noset and a_no and not a_yes:
            return "correct"
        return "wrong"
    # 实体题：gold 实体名出现在答案里（任一方向）
    return "correct" if (g in a or a in g) else "wrong"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv(_ROOT / ".env")
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY 未设置")
    model = "deepseek-chat"
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    client = OpenAI(api_key=api_key, base_url=base_url)

    cases = load_cases()
    rows = []
    for c in cases:
        resp = client.chat.completions.create(
            model=model, temperature=0,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": c["question"]}],
        )
        ans = (resp.choices[0].message.content or "").strip()
        verdict = judge(c["gold_answer"], ans)
        kind = "实体" if c["qid"] in ENTITY_QIDS else "yes/no"
        rows.append({**c, "kind": kind, "deepseek": ans, "verdict": verdict})

    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{'='*100}")
    for r in rows:
        mark = {"correct": "✓", "wrong": "✗", "unknown": "?"}[r["verdict"]]
        print(f"\n[{mark} {r['kind']}] {r['qid']}  gold={r['gold_answer']!r}")
        print(f"  Q: {r['question'][:130]}")
        print(f"  deepseek闭卷: {r['deepseek'][:200]}")

    def tally(kind):
        sub = [r for r in rows if r["kind"] == kind]
        c = sum(1 for r in sub if r["verdict"] == "correct")
        u = sum(1 for r in sub if r["verdict"] == "unknown")
        return c, u, len(sub)

    ec, eu, en = tally("实体")
    yc, yu, yn = tally("yes/no")
    print(f"\n{'='*100}\n闭卷泄漏汇总：")
    print(f"  实体题（强信号）: 答对 {ec}/{en}（UNKNOWN {eu}）")
    print(f"  yes/no 题（50%基线）: 答对 {yc}/{yn}（UNKNOWN {yu}）")
    print(f"  → 实体题答对率高 = 语料泄漏进 deepseek，实体推断捷径=记忆驱动、私有语料会失效")
    print(f"详细已写 {OUT}")


if __name__ == "__main__":
    main()
