"""MultiHop-RAG 共享图构建。

把全部文档摄入**同一个**持久化 MCS 实例，支持断点续跑。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from mcs import MCSConfig
from mcs.core.plugin import PluginType
from mcs.plugins.preprocess.source_tracking import IdempotencyCheckPlugin
from mcs.presets import Phase1Builder

from bench.multihop_rag.data import MultiHopDoc

logger = logging.getLogger(__name__)


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

    mcs.write_pipeline.llm.attach_recorder(_rec)
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
    max_accumulated_nodes: int | None = None,
    max_rounds: int | None = None,
    llm_config: dict | None = None,
) -> Any:
    """创建一个配置好持久化与 LLM key 的 MCS 实例（已 initialize）。

    ``token_budget`` 设核心不变量阈值 T（如 32000）。``record_path`` 非空时挂载
    JSONL LLM 调用记录器。``rerank=True`` 时把 query_postprocess 重排插件加入插件链
    （opt-in）。``max_accumulated_nodes`` / ``max_rounds`` 非 None 时放宽遍历参数。
    """
    config = MCSConfig.knowledge_graph(write_llm=llm, read_llm=llm)
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
    if max_accumulated_nodes is not None:
        config.max_accumulated_nodes = max_accumulated_nodes
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
        # 从配置文件读取 claude 端点（base_url/auth_token/model/timeout/max_tokens），
        # 支持官方端点与兼容网关（如反代第三方模型的 Messages 协议网关）。不读环境变量。
        ccfg = (llm_config or {}).get("claude", {})
        config.plugin_configs["claude_llm"].update(
            {
                "auth_token": ccfg.get("auth_token", ""),
                "base_url": ccfg.get("base_url", "https://api.anthropic.com"),
                "model": ccfg.get("model", "claude-3-5-sonnet-latest"),
                "timeout": float(ccfg.get("timeout", 60.0)),
                "max_tokens": int(ccfg.get("max_tokens", 4096)),
            }
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
    max_accumulated_nodes: int | None = None,
    max_rounds: int | None = None,
    llm_config: dict | None = None,
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
        max_accumulated_nodes=max_accumulated_nodes,
        max_rounds=max_rounds,
        llm_config=llm_config,
    )
    # 定位幂等插件：mcs.ingest() 路径本身不查 document_chunks（跳过逻辑只在
    # SourceTrackingPlugin.update_document 里，bench 不走它），故断点续跑必须在此
    # 显式跳过已摄入的块——否则每次重跑都从头全量重做、白烧 LLM 且 re-merge 糊已建节点。
    idem = next(
        (
            p
            for p in mcs.write_pipeline.plugin_manager.get_all(
                PluginType.WRITE_PREPROCESS
            )
            if isinstance(p, IdempotencyCheckPlugin)
        ),
        None,
    )
    total = len(docs)
    skipped = 0
    for di, doc in enumerate(docs, 1):
        if whole_doc:
            # 整篇摄入：标题+正文作为单个单元（chunk_id=0），文本 100% 覆盖。
            body = (doc.body or "").strip()
            units = [f"{doc.title}: {body}".strip()] if (body or doc.title) else []
        else:
            units = chunk_body(doc.title, doc.body, max_chunks_per_doc)
        for ci, text in enumerate(units):
            # 幂等跳过：已成功摄入的块不再进管线（零 LLM、不 re-merge）
            if idem is not None and idem.is_ingested(
                doc.title, str(ci),
                hashlib.sha256(text.encode("utf-8")).hexdigest(),
            ):
                skipped += 1
                continue
            try:
                mcs.ingest(
                    text,
                    doc_id=doc.title,
                    chunk_id=str(ci),
                    section_title=doc.title,
                )
            except Exception:
                logger.warning(
                    "ingest 失败: doc=%r chunk=%d，跳过", doc.title, ci, exc_info=True
                )
        if di == 1 or di % 5 == 0 or di == total:
            print(f"  building graph: {di}/{total} docs (skipped {skipped})")
        # 周期性全量重建持久化：反映分层归纳产生的边删除/重挂（增量持久化只 upsert）
        if di % 25 == 0:
            try:
                mcs.store.save_full()
            except Exception:
                logger.warning("save_full 失败 @doc %d，继续", di)
    try:
        mcs.store.save_full()  # 收尾：使持久图与内存图完全一致
    except Exception:
        logger.warning("最终 save_full 失败")
    return mcs