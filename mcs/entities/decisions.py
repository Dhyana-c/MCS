"""写入管道 ④⑤ 和提示共享的 DecisionList 数据结构。

参见 openspec/specs/write-pipeline/spec.md "DecisionList 至少支持三种 action"
和 openspec/specs/phase1-defaults/spec.md "DecisionList 派发三种 action"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from mcs.entities.graph import CLASS_CONCEPT, CLASS_EVENT

ActionType = Literal["merge", "create", "no_op"]


@dataclass
class ConceptDraft:
    """从文本中提取的一个概念或事实（写入阶段 ③ 输出）。

    ``relation_hints`` 是 LLM 在提取过程中识别的自然语言关系短语列表
    （例如"属于机器学习"、"由小明发明"），用于阶段 ④ 判断概念间的边连接。

    ``node_class`` 区分概念与事实：概念是名词性实体，事实是含谓词的命题陈述。
    默认为 ``CLASS_CONCEPT``（向后兼容）。
    """

    name: str
    content: str
    relation_hints: list[str] = field(default_factory=list)
    node_class: str = CLASS_CONCEPT  # 概念 / 事实


@dataclass
class Decision:
    """DecisionList 中的一个动作（写入阶段 ④ 输出，⑤ 输入）。

    字段有效性取决于 ``action``：
      - merge:  concept, target_id
      - create: concept, [edges_to], [edges_to_names], [node_class]
      - no_op:  concept, reason

    ``edges_to`` 是到**已存在节点**的锚点列表（每项含 target_id）；
    ``edges_to_names`` 是到**同一批新概念**的概念名列表（每项含 target_name）——
    写入阶段 ⑤ 在新节点全部建好后按名解析成边，弥补"同次摄入的兄弟概念之间无法用
    id 互连"的缺口。统一模型下这些边为 ``关联`` 边（无 label、无 kind；开放谓词
    落事实节点 content）。一条关系 = 一个方向，不自动镜像反向。

    ``node_class`` 决定 create 时新建节点的类型：概念（默认）或事实。
    事实节点的谓词语义落 content，可被事件背书、可与其他事实互斥。

    ``mutex_with`` 是与**已有事实节点**互斥的 id 列表（阶段 ⑤ 第一遍后创建互斥边）。
    ``mutex_with_names`` 是与**同批新事实**互斥的概念名列表（第二遍按名解析后创建互斥边）。
    互斥仅适用于事实 ↔ 事实，概念间 mutex_with 被忽略。
    """

    action: ActionType
    concept: ConceptDraft | None = None
    target_id: str | None = None
    edges_to: list[dict] = field(default_factory=list)  # [{"target_id": str}, ...]
    edges_to_names: list[dict] = field(default_factory=list)  # [{"target_name": str}, ...]
    aliases_to_add: list[str] = field(default_factory=list)
    reason: str | None = None
    node_class: str = CLASS_CONCEPT  # create 时：概念 / 事实
    mutex_with: list[str] = field(default_factory=list)  # 已有事实 id（互斥边）
    mutex_with_names: list[str] = field(default_factory=list)  # 同批新事实名（互斥边）


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


@dataclass
class EventData:
    """事件规则入库的结构化输入（不经 LLM）。

    宪法 D5：事件按既定结构直接存，不经 LLM。系统创建 ``CLASS_EVENT`` 节点
    并对 ``target_ids`` 中每个 id 创建 ``事件 → 目标`` 的 ``EDGE_ASSOC`` 边
    （背书·提及，方向固定）。

    ``target_ids`` 是本事件背书/提及的核心节点 id（事实 / 概念）。
    ``timestamp`` 存入 ``extensions["event_meta"]["timestamp"]``。
    """

    name: str
    content: str
    timestamp: str | None = None  # ISO 8601
    target_ids: list[str] = field(default_factory=list)
    extensions: dict[str, Any] = field(default_factory=dict)
