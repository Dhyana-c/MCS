"""公共 content 合并 helper。

统一 3 条字面合并路径的 content 处理（write path / query read-repair / 后台 dedup），
落实 unified-graph-schema「图质量最终收敛」content 合并守则：不机械换行追加。

行为：
- 子串关系（target ⊇ incoming → 跳过；incoming ⊇ target → 替换）→ 零成本，所有路径共用。
- 非子串 + merge_llm 传入 → LLM 语义合并成一个稳定定义（守时间归属）。
- 非子串 + merge_llm=None → 返回 target（不碰；调用方决定挂起 / 保留 dup）。

调用方分流（按 LLM 可用性）：
- write path `_dispatch_merge` 传 merge_llm（每次 ingest 同名对齐，本就 LLM）。
- query read-repair `_try_read_repair` 不传（读路径零 LLM；被并方节点保留）。
- 后台 dedup 不传（子串才合删 dup，非子串保留 dup；彻底合并靠 write path）。
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def merge_content(
    target: str,
    incoming: str,
    merge_llm: Optional[Callable[[str, str], str]] = None,
) -> str:
    """合并两段 content 成一个稳定定义（不机械换行追加）。

    - 子串关系零成本（target ⊇ incoming 跳过；incoming ⊇ target 替换）。
    - 非子串 + merge_llm：LLM 语义合并；异常 / 空返回 → 降级保留 target + warning。
    - 非子串 + merge_llm=None：返回 target（不碰）。
    - target 空 → incoming；incoming 空 → target。
    """
    t = target or ""
    i = incoming or ""

    if not i.strip():
        return target
    if not t.strip():
        return incoming

    # 子串关系零成本
    if i in t:
        return target  # incoming 已含于 target，跳过
    if t in i:
        return incoming  # target 是 incoming 子串，替换

    # 非子串
    if merge_llm is None:
        return target  # 读路径 / dedup：不碰

    try:
        merged = merge_llm(target, incoming)
    except Exception:
        logger.warning("merge_content: LLM 合并失败，保留 target content", exc_info=True)
        return target
    if not merged or not merged.strip():
        logger.warning("merge_content: LLM 返回空，保留 target content")
        return target
    return merged.strip()
