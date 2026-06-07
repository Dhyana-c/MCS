"""MultiHop-RAG 共享语料多跳检索评测。

与 hotpot bench 相反，这里是"一次建图、多 query"：把整个语料摄入**同一个持久化
MCS 实例**（SQLite，非 :memory:），之后对所有 query 做检索评测。主指标是**文档级
检索召回** Hit@k / MAP@k / MRR@k——把 query() 返回的 List[Node] 经 source_tracking
映射回来源文档，与 gold evidence 的来源文档比对。绕开"MCS 不是答题器"的弱点。

数据：从 HuggingFace ``yixuantt/MultiHop-RAG`` 下载，本地放在
``D:\\code\\hotpot\\MultiHopRAG\\``（multihoprag_corpus.json + multihoprag_qa.json）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CORPUS = r"D:\code\hotpot\MultiHopRAG\multihoprag_corpus.json"
DEFAULT_QA = r"D:\code\hotpot\MultiHopRAG\multihoprag_qa.json"

# 实测 token 模型（来自 hotpot 真账单反推）：约 9K token/段，input¥0.5/M + output¥2/M
_TOKENS_IN_PER_CHUNK = 7500
_TOKENS_OUT_PER_CHUNK = 1500
_PRICE_IN_PER_M = 0.5  # ¥/1M（deepseek-chat cache-miss 近似，请按当前价核对）
_PRICE_OUT_PER_M = 2.0  # ¥/1M


def _ensure_utf8_stdout() -> None:
    """stdout 切 UTF-8 + errors='replace'，避免 Windows GBK 控制台遇非 GBK 字符崩溃。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _maybe_load_dotenv() -> None:
    """若存在 .env（项目根或当前目录），把其中的键值灌进环境变量。"""
    for p in (Path("D:/code/mcs/.env"), Path(".env")):
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        return


# ─── 1. 数据加载 ───────────────────────────────────────────────────────────────


@dataclass
class MultiHopDoc:
    """语料中的一篇文档（以 title 作为文档标识）。"""

    title: str
    body: str
    source: str = ""
    published_at: str = ""
    url: str = ""
    author: str = ""
    category: str = ""


@dataclass
class Evidence:
    """一条证据，指向某篇文档的某个片段。"""

    title: str
    url: str = ""
    source: str = ""
    fact: str = ""
    published_at: str = ""


@dataclass
class MultiHopQuery:
    """一个多跳查询。"""

    query: str
    answer: str
    question_type: str  # inference_query | comparison_query | temporal_query | null_query
    evidence_list: list[Evidence] = field(default_factory=list)

    @property
    def query_id(self) -> str:
        return hashlib.md5(self.query.encode("utf-8")).hexdigest()[:12]

    @property
    def gold_doc_titles(self) -> set[str]:
        return {e.title for e in self.evidence_list if e.title}


class MultiHopDataLoader:
    """读取 MultiHop-RAG 语料与查询；支持 corpus 子集 + query 同步过滤。"""

    def __init__(
        self,
        corpus_path: str = DEFAULT_CORPUS,
        queries_path: str = DEFAULT_QA,
        corpus_subset: int | None = None,
        seed: int = 42,
    ):
        self.corpus_path = corpus_path
        self.queries_path = queries_path
        self.corpus_subset = corpus_subset
        self.seed = seed

    def load(self) -> tuple[list[MultiHopDoc], list[MultiHopQuery]]:
        for p in (self.corpus_path, self.queries_path):
            if not Path(p).exists():
                raise FileNotFoundError(
                    f"MultiHop-RAG 数据缺失: {p}\n"
                    "请从 HuggingFace `yixuantt/MultiHop-RAG` 下载 "
                    "multihoprag_corpus.json 与 multihoprag_qa.json。"
                )
        with open(self.corpus_path, encoding="utf-8") as f:
            corpus_raw = json.load(f)
        with open(self.queries_path, encoding="utf-8") as f:
            qa_raw = json.load(f)

        docs = [self._parse_doc(d) for d in corpus_raw]
        queries = [self._parse_query(q) for q in qa_raw]

        if self.corpus_subset is not None:
            import random

            rng = random.Random(self.seed)
            docs = rng.sample(docs, min(self.corpus_subset, len(docs)))
            sampled = {d.title for d in docs}
            # 只保留证据来源文档全部落在子集内的 query（null_query 证据为空 → 始终保留）
            queries = [q for q in queries if q.gold_doc_titles <= sampled]
            logger.info(
                "子集: %d 篇文档, 过滤后 %d 个可达 query", len(docs), len(queries)
            )
        return docs, queries

    @staticmethod
    def _parse_doc(d: dict) -> MultiHopDoc:
        return MultiHopDoc(
            title=d["title"],
            body=d.get("body", ""),
            source=d.get("source", ""),
            published_at=d.get("published_at", ""),
            url=d.get("url", ""),
            author=d.get("author", "") or "",
            category=d.get("category", "") or "",
        )

    @staticmethod
    def _parse_query(q: dict) -> MultiHopQuery:
        return MultiHopQuery(
            query=q["query"],
            answer=q.get("answer", ""),
            question_type=q.get("question_type", ""),
            evidence_list=[
                Evidence(
                    title=e.get("title", ""),
                    url=e.get("url", ""),
                    source=e.get("source", ""),
                    fact=e.get("fact", ""),
                    published_at=e.get("published_at", ""),
                )
                for e in q.get("evidence_list", [])
            ],
        )


def filter_queries(
    queries: list[MultiHopQuery], exclude_null: bool
) -> list[MultiHopQuery]:
    """可选地排除 ``null_query``（语料中无答案的诊断项）。

    小 corpus 子集下 null_query 占比极高、干扰检索信号；``--exclude-null`` 开启时
    只评非 null 的可达 query。
    """
    if not exclude_null:
        return queries
    return [q for q in queries if q.question_type != "null_query"]


# ─── 2. 共享图构建 ─────────────────────────────────────────────────────────────


def chunk_body(title: str, body: str, max_chunks: int = 8) -> list[str]:
    """把文档正文切成若干块（按段落，过长段落再按句子切），并截断到 max_chunks。

    第一块前置标题，给 MCS 一点文档上下文。
    """
    parts = [p.strip() for p in re.split(r"\n{1,}", body) if p.strip()]
    if not parts:
        parts = [body.strip()] if body.strip() else []
    chunks: list[str] = []
    for p in parts:
        if len(p) > 1200:
            buf = ""
            for s in re.split(r"(?<=[.!?])\s+", p):
                if buf and len(buf) + len(s) > 1200:
                    chunks.append(buf.strip())
                    buf = ""
                buf += " " + s
            if buf.strip():
                chunks.append(buf.strip())
        else:
            chunks.append(p)
    chunks = [c for c in chunks if c][:max_chunks]
    if chunks:
        chunks[0] = f"{title}: {chunks[0]}"
    return chunks


def _attach_llm_recorder(mcs: Any, record_path: str) -> None:
    """给 mcs 的 LLM 挂一个 JSONL 调用记录器（append 写入，支持续跑追加）。

    每次 LLM 调用落一行：purpose/model/system/user/raw/latency/parse_error。
    文件句柄挂在 mcs 上保活，flush-per-line 确保进程被杀也不丢已写记录。
    """
    import threading

    Path(record_path).parent.mkdir(parents=True, exist_ok=True)
    fh = open(record_path, "a", encoding="utf-8")
    lock = threading.Lock()

    def _rec(record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False)
        with lock:
            fh.write(line + "\n")
            fh.flush()

    mcs.llm.attach_recorder(_rec)
    mcs._llm_record_fh = fh  # 保活，避免句柄被 GC 关闭


def _make_mcs(
    llm: str,
    db_path: str,
    *,
    token_budget: int = 8000,
    record_path: str | None = None,
    rerank: bool = False,
    rerank_top_n: int | None = None,
    rerank_min_score: float = 0.0,
    max_picked: int | None = None,
    max_rounds: int | None = None,
) -> Any:
    """创建一个配置好持久化与 LLM key 的 MCS 实例（已 initialize）。

    ``token_budget`` 设核心不变量阈值 T（如 32000）。``record_path`` 非空时挂载
    JSONL LLM 调用记录器。``rerank=True`` 时把 query_postprocess 重排插件加入插件链
    （opt-in）。``max_picked`` / ``max_rounds`` 非 None 时放宽遍历宽度/轮数。
    """
    from mcs import MCSConfig
    from mcs.presets import Phase1Builder

    config = MCSConfig.knowledge_graph(write_llm=llm, read_llm=llm)
    config.seed_graph_bounding = True  # 开启虚拟根节点 + fanout reduce
    config.token_budget = token_budget  # 核心不变量阈值 T（如 32k）
    # 评测可选关闭逐节点摘要重生（summary_regen）：文档级检索不直接依赖摘要文本，
    # 关掉可省 ~2.6× LLM 调用（摘要渲染回退到 content[:200]）。用于本地慢后端提速。
    if os.environ.get("MCS_NO_SUMMARY_REGEN", "0").lower() in ("1", "true", "yes"):
        if "summary_regen" in config.write_plugins:
            config.write_plugins.remove("summary_regen")
    # 评测可选去掉"关键词召回"(alias_entry)：种子只来自 hub_fallback 的种子图导航
    # (从持久根下钻)，用于隔离评估分层种子图本身的检索能力。build 走 resume 时被
    # 幂等跳过，故只影响查询阶段，不改已建图。
    if os.environ.get("MCS_NO_ALIAS_ENTRY", "0").lower() in ("1", "true", "yes"):
        if "alias_entry" in config.read_plugins:
            config.read_plugins.remove("alias_entry")
    config.plugin_configs["sqlite_storage"] = {"path": db_path}
    if max_picked is not None:
        config.max_picked = max_picked
    if max_rounds is not None:
        config.max_rounds = max_rounds
    if rerank:
        if "rerank" not in config.read_plugins:
            config.read_plugins.append("rerank")
        config.plugin_configs["rerank"] = {
            "scorer": "lexical",
            "top_n": rerank_top_n,
            "min_score": rerank_min_score,
        }
    if llm == "deepseek":
        ds = config.plugin_configs["deepseek_llm"]
        ds["api_key"] = os.environ.get("DEEPSEEK_API_KEY", "")
        # 模型/base_url 可经环境变量覆盖（如 DEEPSEEK_MODEL=deepseek-v4-flash）
        if os.environ.get("DEEPSEEK_MODEL"):
            ds["model"] = os.environ["DEEPSEEK_MODEL"]
        if os.environ.get("DEEPSEEK_BASE_URL"):
            ds["base_url"] = os.environ["DEEPSEEK_BASE_URL"]
    elif llm == "claude":
        config.plugin_configs["claude_llm"]["auth_token"] = os.environ.get(
            "ANTHROPIC_API_KEY", ""
        )
    elif llm == "ollama":
        # think 默认关闭（OLLAMA_THINK=1 可开）；思维模型开 thinking 会把每次调用
        # 从秒级拖到分钟级，整图 build 实际跑不完。
        think = os.environ.get("OLLAMA_THINK", "0").lower() in ("1", "true", "yes")
        config.plugin_configs["ollama_llm"].update({
            "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            "model": os.environ.get("OLLAMA_MODEL", ""),
            "max_tokens": 32768,
            "timeout": 300,
            "think": think,
            # 整篇摄入时调大上下文窗口（OLLAMA_NUM_CTX），避免长文档被静默截断。
            "num_ctx": int(os.environ.get("OLLAMA_NUM_CTX", "8192")),
        })
    builder = Phase1Builder(config)
    mcs = builder.build()
    if record_path:
        _attach_llm_recorder(mcs, record_path)
    return mcs


def build_shared_graph(
    docs: list[MultiHopDoc],
    llm: str = "deepseek",
    db_path: str = "./multihop_bench.db",
    max_chunks_per_doc: int = 8,
    *,
    whole_doc: bool = False,
    token_budget: int = 8000,
    record_path: str | None = None,
    rerank: bool = False,
    rerank_top_n: int | None = None,
    rerank_min_score: float = 0.0,
    max_picked: int | None = None,
    max_rounds: int | None = None,
) -> Any:
    """把全部文档摄入**同一个**持久化 MCS 实例，返回该实例。

    依赖 idempotency_check：重复构建时已摄入的文档块自动跳过（断点续跑）。
    ``token_budget`` / ``record_path`` / ``rerank`` 等参数透传给 ``_make_mcs``。
    """
    mcs = _make_mcs(
        llm,
        db_path,
        token_budget=token_budget,
        record_path=record_path,
        rerank=rerank,
        rerank_top_n=rerank_top_n,
        rerank_min_score=rerank_min_score,
        max_picked=max_picked,
        max_rounds=max_rounds,
    )
    total = len(docs)
    for di, doc in enumerate(docs, 1):
        if whole_doc:
            # 整篇摄入：标题+正文作为单个单元（chunk_id=0），文本 100% 覆盖。
            body = (doc.body or "").strip()
            units = [f"{doc.title}: {body}".strip()] if (body or doc.title) else []
        else:
            units = chunk_body(doc.title, doc.body, max_chunks_per_doc)
        for ci, text in enumerate(units):
            try:
                mcs.ingest(
                    text,
                    doc_id=doc.title,
                    chunk_id=str(ci),
                    section_title=doc.title,
                )
            except Exception:
                logger.warning("ingest 失败: doc=%r chunk=%d，跳过", doc.title, ci)
        if di == 1 or di % 5 == 0 or di == total:
            print(f"  building graph: {di}/{total} docs")
        # 周期性全量重建持久化：反映分层归纳产生的边删除/重挂（增量持久化只 upsert）
        if di % 25 == 0:
            try:
                mcs.persist_full()
            except Exception:
                logger.warning("persist_full 失败 @doc %d，继续", di)
    try:
        mcs.persist_full()  # 收尾：使持久图与内存图完全一致
    except Exception:
        logger.warning("最终 persist_full 失败")
    return mcs


# ─── 3. 查询 → 证据映射 ────────────────────────────────────────────────────────


def retrieved_docs(nodes: list[Any]) -> list[str]:
    """把 query() 返回的节点（按 rank）映射成"按 rank 去重的来源文档列表"。

    一个概念节点可能来自多篇文档（merge 后）→ 取其来源并集。
    """
    seen: set[str] = set()
    ranked: list[str] = []
    for node in nodes:
        sources = (
            (getattr(node, "extensions", {}) or {})
            .get("source_tracking", {})
            .get("sources", [])
        )
        for s in sources:
            doc = s.doc_id if hasattr(s, "doc_id") else (
                s.get("doc_id") if isinstance(s, dict) else None
            )
            if doc and doc not in seen:
                seen.add(doc)
                ranked.append(doc)
    return ranked


# ─── 4. 检索指标 ───────────────────────────────────────────────────────────────


def recall_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    if not gold:
        return 0.0
    return len(set(ranked[:k]) & gold) / len(gold)


def hit_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    """是否在 top-k 命中至少一个 gold 文档。"""
    if not gold:
        return 0.0
    return 1.0 if (set(ranked[:k]) & gold) else 0.0


def map_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    if not gold:
        return 0.0
    hits = 0
    score = 0.0
    for i, d in enumerate(ranked[:k], 1):
        if d in gold:
            hits += 1
            score += hits / i
    return score / min(len(gold), k)


def mrr_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    for i, d in enumerate(ranked[:k], 1):
        if d in gold:
            return 1.0 / i
    return 0.0


def _mean(xs: list[float]) -> float:
    return statistics.fmean(xs) if xs else 0.0


def aggregate_metrics(
    results: list[dict], k_values: list[int]
) -> dict[str, dict]:
    """按 question_type 与总体聚合检索指标；null_query 单独诊断。"""
    buckets: dict[str, list[dict]] = {}
    null_docs: list[int] = []
    for r in results:
        if r["type"] == "null_query":
            null_docs.append(len(r["ranked"]))
            continue
        buckets.setdefault(r["type"], []).append(r)
        buckets.setdefault("overall", []).append(r)

    out: dict[str, dict] = {}
    for name, rs in buckets.items():
        m: dict[str, float] = {"n": len(rs)}
        for k in k_values:
            golds = [set(r["gold"]) for r in rs]
            ranks = [r["ranked"] for r in rs]
            m[f"hit@{k}"] = _mean([hit_at_k(rk, g, k) for rk, g in zip(ranks, golds)])
            m[f"recall@{k}"] = _mean(
                [recall_at_k(rk, g, k) for rk, g in zip(ranks, golds)]
            )
            m[f"map@{k}"] = _mean([map_at_k(rk, g, k) for rk, g in zip(ranks, golds)])
            m[f"mrr@{k}"] = _mean([mrr_at_k(rk, g, k) for rk, g in zip(ranks, golds)])
        out[name] = m
    out["null_query"] = {
        "n": len(null_docs),
        "avg_docs_retrieved": _mean([float(x) for x in null_docs]),
    }
    return out


# ─── 5. 评测运行器 ─────────────────────────────────────────────────────────────


@dataclass
class MultiHopEvalConfig:
    corpus_path: str = DEFAULT_CORPUS
    queries_path: str = DEFAULT_QA
    corpus_subset: int | None = None
    llm_backend: str = "deepseek"
    token_budget: int = 8000  # 核心不变量阈值 T（如 32000）
    db_path: str = "./multihop_bench.db"
    output_dir: str = "./multihop_output"
    k_values: list[int] = field(default_factory=lambda: [2, 4, 10])
    max_chunks_per_doc: int = 8
    whole_doc: bool = False  # 整篇摄入（不切块）：标题+正文作为单个单元，文本100%覆盖
    resume: bool = True
    dry_run: bool = False
    seed: int = 42
    exclude_null: bool = False  # 排除 null_query（只评非 null 的可达 query）
    rerank: bool = True  # query 阶段相关性重排（默认开；实测 hit@10 0.16→0.73，零额外 LLM）
    rerank_top_n: int | None = 50  # 重排后截断 top-N（仅 rerank=True 时生效）
    rerank_min_score: float = 0.0  # 重排过滤阈值（默认不误杀）
    max_picked: int | None = None  # 放宽遍历累积上限（None=用默认 50）
    max_rounds: int | None = None  # 放宽遍历轮数（None=用默认 5）
    doc_rerank: bool = False  # 文档级重排（bench-only，与节点级 --rerank 正交）
    doc_rerank_top_n: int | None = None  # 文档级重排截断 top-N（None=不截断）


class MultiHopEvalRunner:
    def __init__(self, config: MultiHopEvalConfig | None = None):
        self.config = config or MultiHopEvalConfig()

    def run(self) -> dict[str, dict]:
        _ensure_utf8_stdout()
        from mcs.bench.doc_rerank import doc_rerank

        cfg = self.config
        out = Path(cfg.output_dir)
        out.mkdir(parents=True, exist_ok=True)

        loader = MultiHopDataLoader(
            cfg.corpus_path, cfg.queries_path, cfg.corpus_subset, cfg.seed
        )
        docs, queries = loader.load()
        queries = filter_queries(queries, cfg.exclude_null)
        suffix = "（已排除 null_query）" if cfg.exclude_null else ""
        print(f"语料 {len(docs)} 篇文档, {len(queries)} 个可达 query{suffix}")
        if cfg.rerank:
            print(
                f"重排已启用：scorer=lexical top_n={cfg.rerank_top_n} "
                f"min_score={cfg.rerank_min_score}"
            )
        if cfg.doc_rerank:
            print(f"文档级重排已启用（bench-only）：top_n={cfg.doc_rerank_top_n}")

        # 构建（或复用）共享图
        print("构建共享图（已摄入的会自动跳过）…")
        if cfg.whole_doc:
            print("整篇摄入模式：每篇文档作为单个单元（不切块），文本 100% 覆盖")
        mcs = build_shared_graph(
            docs,
            cfg.llm_backend,
            cfg.db_path,
            cfg.max_chunks_per_doc,
            whole_doc=cfg.whole_doc,
            token_budget=cfg.token_budget,
            record_path=str(out / "llm_calls.jsonl"),
            rerank=cfg.rerank,
            rerank_top_n=cfg.rerank_top_n,
            rerank_min_score=cfg.rerank_min_score,
            max_picked=cfg.max_picked,
            max_rounds=cfg.max_rounds,
        )

        # 断点续跑：复用已落盘的检索结果
        results_file = out / "retrieval_results.json"
        results: dict[str, dict] = {}
        if cfg.resume and results_file.exists():
            try:
                results = json.loads(results_file.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("无法读取已有 retrieval_results.json，从头开始")
        done = set(results)

        def _persist() -> None:
            results_file.write_text(
                json.dumps(results, ensure_ascii=False), encoding="utf-8"
            )

        total = len(queries)
        for i, q in enumerate(queries, 1):
            if q.query_id in done:
                continue
            try:
                nodes = mcs.query(q.query)
                nodes = nodes if isinstance(nodes, list) else []
            except Exception:
                logger.exception("query 失败: %s", q.query_id)
                nodes = []
            if cfg.doc_rerank:
                ranked = doc_rerank(nodes, q.query, top_n=cfg.doc_rerank_top_n)
            else:
                ranked = retrieved_docs(nodes)
            results[q.query_id] = {
                "type": q.question_type,
                "gold": sorted(q.gold_doc_titles),
                "ranked": ranked,
            }
            if i % 20 == 0 or i == total:
                print(f"  query {i}/{total}")
            _persist()

        mcs.shutdown()

        metrics = aggregate_metrics(list(results.values()), cfg.k_values)
        self._print_metrics(metrics)
        (out / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return metrics

    def dry_run(self) -> dict[str, Any]:
        _ensure_utf8_stdout()
        cfg = self.config
        loader = MultiHopDataLoader(
            cfg.corpus_path, cfg.queries_path, cfg.corpus_subset, cfg.seed
        )
        docs, queries = loader.load()
        total_chunks = sum(
            len(chunk_body(d.title, d.body, cfg.max_chunks_per_doc)) for d in docs
        )
        in_tok = total_chunks * _TOKENS_IN_PER_CHUNK
        out_tok = total_chunks * _TOKENS_OUT_PER_CHUNK
        cost = in_tok * _PRICE_IN_PER_M / 1e6 + out_tok * _PRICE_OUT_PER_M / 1e6
        est = {
            "docs": len(docs),
            "queries": len(queries),
            "total_chunks": total_chunks,
            "build_tokens_estimated": in_tok + out_tok,
            "build_cost_cny_estimated": round(cost, 2),
            "note": "仅首建图成本；query 阶段只走查询管线，成本低得多",
        }
        print("\n=== MultiHop-RAG Dry Run（首建图估算）===")
        for k, v in est.items():
            print(f"  {k}: {v}")
        return est

    @staticmethod
    def _print_metrics(metrics: dict[str, dict]) -> None:
        print("\n=== MultiHop-RAG 检索指标（文档级）===")
        for name in ["overall", "inference_query", "comparison_query", "temporal_query"]:
            m = metrics.get(name)
            if not m:
                continue
            parts = " ".join(
                f"{key}={val:.3f}"
                for key, val in m.items()
                if key != "n"
            )
            print(f"  [{name} n={m['n']}] {parts}")
        nq = metrics.get("null_query", {})
        if nq:
            print(
                f"  [null_query n={nq.get('n', 0)}] "
                f"avg_docs_retrieved={nq.get('avg_docs_retrieved', 0):.2f}"
            )


# ─── 6. CLI 入口 ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="MCS MultiHop-RAG 检索评测")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS)
    parser.add_argument("--queries", default=DEFAULT_QA)
    parser.add_argument(
        "--corpus-subset", type=int, default=0, help="采样 N 篇文档（0=全量）"
    )
    parser.add_argument("--llm", choices=["deepseek", "claude", "ollama"], default="deepseek")
    parser.add_argument(
        "--token-budget",
        type=int,
        default=8000,
        help="核心不变量阈值 T（如 32000）；建图守门与查询子图共用",
    )
    parser.add_argument("--db", default="./multihop_bench.db")
    parser.add_argument("--output", default="./multihop_output")
    parser.add_argument(
        "--k", default="2,4,10", help="逗号分隔的 k 列表，如 2,4,10"
    )
    parser.add_argument("--max-chunks", type=int, default=8)
    parser.add_argument(
        "--whole-doc",
        action="store_true",
        help="整篇摄入（不切块）：标题+正文作为单个单元，文本 100%% 覆盖（长文档需调大 OLLAMA_NUM_CTX）",
    )
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--exclude-null",
        action="store_true",
        help="排除 null_query，只评非 null 的可达 query",
    )
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="关闭相关性重排（默认开；重排为查询侧 lexical、复用现有图、不重建）",
    )
    parser.add_argument(
        "--rerank-top-n",
        type=int,
        default=50,
        help="重排后截断 top-N（0 = 不截断；默认 50）",
    )
    parser.add_argument(
        "--rerank-min-score",
        type=float,
        default=0.0,
        help="重排过滤阈值，低于该分的节点被丢弃（默认 0.0 不误杀）",
    )
    parser.add_argument(
        "--max-picked",
        type=int,
        default=0,
        help="放宽遍历累积上限（0=用默认 50；广召回时调大，如 150）",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=0,
        help="放宽遍历轮数（0=用默认 5；广召回时调大，如 8）",
    )
    parser.add_argument(
        "--doc-rerank",
        action="store_true",
        help="启用文档级重排（bench-only，对候选文档直接打分排序，与 --rerank 正交）",
    )
    parser.add_argument(
        "--doc-rerank-top-n",
        type=int,
        default=0,
        help="文档级重排截断 top-N（0=不截断）",
    )
    args = parser.parse_args()

    _maybe_load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    cfg = MultiHopEvalConfig(
        corpus_path=args.corpus,
        queries_path=args.queries,
        corpus_subset=args.corpus_subset if args.corpus_subset > 0 else None,
        llm_backend=args.llm,
        token_budget=args.token_budget,
        db_path=args.db,
        output_dir=args.output,
        k_values=[int(x) for x in args.k.split(",") if x.strip()],
        max_chunks_per_doc=args.max_chunks,
        whole_doc=args.whole_doc,
        resume=not args.no_resume,
        dry_run=args.dry_run,
        exclude_null=args.exclude_null,
        rerank=not args.no_rerank,
        rerank_top_n=args.rerank_top_n if args.rerank_top_n > 0 else None,
        rerank_min_score=args.rerank_min_score,
        max_picked=args.max_picked if args.max_picked > 0 else None,
        max_rounds=args.max_rounds if args.max_rounds > 0 else None,
        doc_rerank=args.doc_rerank,
        doc_rerank_top_n=args.doc_rerank_top_n if args.doc_rerank_top_n > 0 else None,
    )
    runner = MultiHopEvalRunner(cfg)
    if cfg.dry_run:
        runner.dry_run()
    else:
        runner.run()


if __name__ == "__main__":
    main()
