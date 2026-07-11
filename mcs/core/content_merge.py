"""公共 content 合并 helper。

统一 3 条字面合并路径的 content 处理（write path / query read-repair / 后台 dedup），
落实 unified-graph-schema「图质量最终收敛」content 合并守则：不机械换行追加。

行为：
- 子串关系（target ⊇ incoming → 跳过；incoming ⊇ target → 替换）→ 零成本，所有路径共用。
- 非子串 + merge_llm 传入 → LLM 语义合并成一个稳定定义（守时间归属）。
- 非子串 + merge_llm=None → 返回 target（不碰；调用方决定挂起 / 保留 dup）。

``substring_relation`` 抽出子串包含判定，供 ``merge_content`` 与后台 dedup 共用——
单点定义，防两处分支口径漂移。

调用方分流（按 LLM 可用性）：
- write path `_dispatch_merge` 传 merge_llm（每次 ingest 同名对齐，本就 LLM）。
- query read-repair `_try_read_repair` 不传（读路径零 LLM；被并方节点保留）。
- 后台 dedup 不传（子串才合删 dup，非子串保留 dup；彻底合并靠 write path）。
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def substring_relation(target: str, incoming: str) -> Optional[str]:
    """两段 content 的子串包含关系（``merge_content`` 与 dedup 共用，防口径漂移）。

    返回：
    - ``"target"``：incoming 为空，或 incoming ⊆ target（target 更全 / 相等）。
    - ``"incoming"``：target 为空，或 target ⊆ incoming（incoming 更全）。
    - ``None``：两方都非空且互不包含（非子串）。

    调用方据此区分「可零成本合并」（返回非 None）与「需 LLM / 保留 dup」（None）。
    """
    t = target or ""
    i = incoming or ""
    if not i.strip():
        return "target"
    if not t.strip():
        return "incoming"
    if i in t:
        return "target"
    if t in i:
        return "incoming"
    return None


def merge_content(
    target: str,
    incoming: str,
    merge_llm: Optional[Callable[[str, str], str]] = None,
) -> str:
    """合并两段 content 成一个稳定定义（不机械换行追加）。

    - 子串关系零成本（经 ``substring_relation``：incoming ⊆ target → target；
      target ⊆ incoming → incoming；含一方空）。
    - 非子串 + merge_llm：LLM 语义合并；异常 / 空返回 → 降级保留 target + warning。
    - 非子串 + merge_llm=None：返回 target（不碰）。
    """
    rel = substring_relation(target, incoming)
    if rel == "target":
        return target
    if rel == "incoming":
        return incoming

    # 非子串（两方都非空、互不包含）
    if merge_llm is None:
        return target

    try:
        merged = merge_llm(target, incoming)
    except Exception:
        logger.warning("merge_content: LLM 合并失败，保留 target content", exc_info=True)
        return target
    if not merged or not merged.strip():
        logger.warning("merge_content: LLM 返回空，保留 target content")
        return target
    return merged.strip()
