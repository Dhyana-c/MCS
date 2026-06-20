"""写入管道 ④⑤ 和提示共享的 DecisionList 数据结构。

参见 openspec/specs/write-pipeline/spec.md "DecisionList 至少支持三种 action"
和 openspec/specs/phase1-defaults/spec.md "DecisionList 派发三种 action"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ActionType = Literal["merge", "create", "no_op"]


@dataclass
class ConceptDraft:
    """从文本中提取的一个概念（写入阶段 ③ 输出）。

    ``relation_hints`` 是 LLM 在提取过程中识别的自然语言关系短语列表
    （例如"属于机器学习"、"由小明发明"），用于阶段 ④ 判断概念间的边连接。
    """

    name: str
    content: str
    relation_hints: list[str] = field(default_factory=list)


@dataclass
class Decision:
    """DecisionList 中的一个动作（写入阶段 ④ 输出，⑤ 输入）。

    字段有效性取决于 ``action``：
      - merge:  concept, target_id
      - create: concept, [edges_to], [edges_to_names]
      - no_op:  concept, reason

    ``edges_to`` 是到**已存在节点**的锚点列表（每项含 target_id）；
    ``edges_to_names`` 是到**同一批新概念**的概念名列表（每项含 target_name）——
    写入阶段 ⑤ 在新节点全部建好后按名解析成边，弥补"同次摄入的兄弟概念之间无法用
    id 互连"的缺口。统一模型下这些边为 ``关联`` 边（无 label、无 kind；开放谓词
    落事实节点 content）。一条关系 = 一个方向，不自动镜像反向。
    """

    action: ActionType
    concept: ConceptDraft | None = None
    target_id: str | None = None
    edges_to: list[dict] = field(default_factory=list)  # [{"target_id": str}, ...]
    edges_to_names: list[dict] = field(default_factory=list)  # [{"target_name": str}, ...]
    aliases_to_add: list[str] = field(default_factory=list)
    reason: str | None = None


DecisionList = list[Decision]


@dataclass
class Community:
    """一进多出聚类中的一个社区。

    每个社区按优先级重组：
    ① 合并同义——把旧的同义概念合并为一
    ② 找到关键概念——识别社区里的关键概念作组织中心
    ③ 概括成新概念——无现成关键概念时概括成一个新概念

    ``member_ids`` 是归属此社区的一跳子节点 id 列表（允许重叠）。
    ``strategy`` 是重组方式："merge" / "key_concept" / "summarize"。
    ``key_concept_id`` 当 strategy=="key_concept" 时，指定关键概念节点 id。
    """

    theme: str
    member_ids: list[str] = field(default_factory=list)
    strategy: str = "summarize"  # "merge" | "key_concept" | "summarize"
    key_concept_id: str | None = None
    summary: str | None = None  # strategy=="summarize" 时的概括内容


@dataclass
class MultiHubDecision:
    """一进多出聚类决策：``decide_hub`` 返回多个社区。

    ``communities`` 是社区列表；``unassigned_ids`` 是无法分类的成员 id
    （确定性兜底：保留在中心节点下，不丢）。
    """

    communities: list[Community] = field(default_factory=list)
    unassigned_ids: list[str] = field(default_factory=list)
    reason: str = ""
