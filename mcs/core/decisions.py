"""写入管道 ④⑤ 和提示共享的 DecisionList 数据结构。

参见 openspec/specs/write-pipeline/spec.md "DecisionList 至少支持四种 action"
和 openspec/specs/phase1-defaults/spec.md "DecisionList 派发四种 action"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ActionType = Literal["merge", "create", "attach_statement", "no_op"]


@dataclass
class ConceptDraft:
    """从文本中提取的一个概念（写入阶段 ③ 输出）。

    ``relation_hints`` 是 LLM 在提取过程中识别的自然语言关系短语列表
    （例如"属于机器学习"、"由小明发明"），阶段 ④ 将其转换为
    ``attach_statement`` 决策。
    """

    name: str
    content: str
    relation_hints: list[str] = field(default_factory=list)


@dataclass
class Decision:
    """DecisionList 中的一个动作（写入阶段 ④ 输出，⑤ 输入）。

    字段有效性取决于 ``action``：
      - merge:             concept, target_id, [aliases_to_add]
      - create:            concept, [edges_to], [edges_to_names], [initial_statements]
      - attach_statement:  target_id（属性节点）, statement
      - no_op:             concept, reason

    ``edges_to`` 是到**已存在节点**的锚点 id；``edges_to_names`` 是到**同一批新概念**
    的概念名（篇内关系）——写入阶段 ⑤ 在新节点全部建好后按名解析成边，弥补"同次摄入
    的兄弟概念之间无法用 id 互连"的缺口。
    """

    action: ActionType
    concept: ConceptDraft | None = None
    target_id: str | None = None
    edges_to: list[str] = field(default_factory=list)
    edges_to_names: list[str] = field(default_factory=list)
    initial_statements: list[str] = field(default_factory=list)
    statement: str | None = None
    aliases_to_add: list[str] = field(default_factory=list)
    reason: str | None = None


DecisionList = list[Decision]


@dataclass
class HubDecision:
    """``decide_hub`` LLM 目的的输出。

    当 LLM 判定没有现有节点适合作为 hub 时，``hub_id`` 为 None，
    应创建一个合成 hub 节点。
    """

    hub_id: str | None
    reason: str = ""
    synthetic_hub_summary: str | None = None
