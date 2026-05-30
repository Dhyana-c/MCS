"""Decision-list data structures shared by write pipeline ④⑤ and prompts.

See openspec/specs/write-pipeline/spec.md "DecisionList 至少支持四种 action"
and openspec/specs/phase1-defaults/spec.md "DecisionList 派发四种 action".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ActionType = Literal["merge", "create", "attach_statement", "no_op"]


@dataclass
class ConceptDraft:
    """One concept extracted from text (write stage ③ output).

    ``relation_hints`` is a list of natural-language relation phrases the
    LLM identified during extraction (e.g. "属于机器学习", "由小明发明")
    that stage ④ turns into ``attach_statement`` decisions.
    """

    name: str
    content: str
    relation_hints: list[str] = field(default_factory=list)


@dataclass
class Decision:
    """One action in the DecisionList (write stage ④ output, ⑤ input).

    Field validity depends on ``action``:
      - merge:             concept, target_id, [aliases_to_add]
      - create:            concept, [edges_to], [initial_statements]
      - attach_statement:  target_id (the attribute node), statement
      - no_op:             concept, reason
    """

    action: ActionType
    concept: ConceptDraft | None = None
    target_id: str | None = None
    edges_to: list[str] = field(default_factory=list)
    initial_statements: list[str] = field(default_factory=list)
    statement: str | None = None
    aliases_to_add: list[str] = field(default_factory=list)
    reason: str | None = None


DecisionList = list[Decision]


@dataclass
class HubDecision:
    """Output of the ``decide_hub`` LLM purpose.

    ``hub_id`` is None when the LLM judges that no existing node is
    suitable and a synthetic hub should be created instead.
    """

    hub_id: str | None
    reason: str = ""
    synthetic_hub_summary: str | None = None
