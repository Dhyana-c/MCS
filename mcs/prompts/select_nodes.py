"""purpose='select_nodes' 的 Prompt 包。

用于查询管线阶段 ② 种子筛选（SeedSelectorPlugin）和
阶段 ③ 遍历循环中的节点选择。输入：候选节点列表 + 查询 + 已累积摘要。
输出：List[node_id] 选中节点的 id 列表。

与 decide_directions 的区别：
  - decide_directions：判断"沿哪个方向扩展"（看邻居背后的潜力）
  - select_nodes：判断"哪些节点与查询直接相关"（语义匹配）
"""

from __future__ import annotations

import json

from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

SYSTEM_PROMPT = (
    "你从候选节点中选出与查询最相关的节点。"
    "只选直接相关的，不要选只是'可能有用'的间接节点。"
    "优先选择包含具体信息的节点，而非笼统的概括。"
    "已经选过的内容不要重复纳入。"
)

USER_TEMPLATE = (
    "查询:\n{query}\n\n"
    "候选节点:\n{material}\n\n"
    "已选节点摘要:\n{accumulated_summary}\n\n"
    "请返回与查询最相关的节点 id 列表 JSON, 例如 [\"id_a\", \"id_b\"]; "
    "若没有相关节点则返回 []。按相关性降序排列。只返回 JSON。"
)


def parse(raw: str) -> list[str]:
    try:
        data = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as e:
        raise LLMParseError("select_nodes", raw, str(e)) from e
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise LLMParseError(
            "select_nodes", raw, "expected JSON array of strings"
        )
    return data