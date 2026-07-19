"""记忆 agent 的工具注册表（可配置工具集）。

12 个内置工具落成 ``ToolSpec`` 注册表 ``BUILTIN_TOOLS``，替代旧 ``loop.py`` 硬编码的
``MEMORY_TOOLS`` 列表 + ``_dispatch`` if/elif。其中 5 个导航 / 写入工具（learn / search /
associate / reason / recall）+ 1 个时间线视图工具（``timeline``，某 universe 事件层按
时间升序、只读不落图）+ 2 个只读语义判断工具（``generalize`` / ``arbitrate``）+
2 个写图语义重组工具（``split`` / ``merge``，调 MCS LLM 插件产方案 + 执行改图、过守门）+
2 个跨 universe 工具（``get_cross_universe_edges`` 只读取桥 / ``link_cross_universe`` 建概念桥）。
只读判断工具不改图、不触发写 / 守门 / 裂变；``learn`` / ``split`` / ``merge`` 为写图工具
（``readonly=False``，排除出只读召回白名单）。工具集经 ``ToolsetConfig`` 启用 / 禁用
子集、按**工具名**覆盖参数。

**导航 / 判断决策权交给 LLM**（不变）：LLM 决定选哪个工具、哪个种子、哪种模式、哪两个
节点、对哪几个节点归纳 / 仲裁。``handler`` 为纯函数（调 ``MemoryStore`` 原语、返回文本，
不做 trace / 异常隔离）；timing + try/except + ``ToolCallTrace`` 保留在
``MemoryAgent._dispatch`` 包装层（见 design D5 / 🟡#3）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from mcs.entities.graph import REALITY_UNIVERSE

__all__ = [
    "ToolSpec",
    "BUILTIN_TOOLS",
    "ToolsetConfig",
    "build_toolset",
    "MEMORY_TOOLS",
]


# === 内置工具 handler（纯：(memory, args) -> 文本；trace/异常隔离在 MemoryAgent._dispatch） ===


def _learn(memory: Any, args: dict) -> str:
    return memory.learn(args.get("text", ""))


def _search(memory: Any, args: dict) -> str:
    return memory.search(
        args.get("query", ""),
        args.get("mode", "keyword"),
        args.get("universe", REALITY_UNIVERSE),
    )


def _associate(memory: Any, args: dict) -> str:
    # limit 从合并 args 取（支持 ToolsetConfig.params 覆盖）；缺省 60（同 MemoryStore.associate）
    return memory.associate(
        args.get("seed_id", ""),
        args.get("mode", "neighbors"),
        limit=args.get("limit", 60),
    )


def _reason(memory: Any, args: dict) -> str:
    # max_hops 从合并 args 取（支持 ToolsetConfig.params 覆盖）；缺省 6（同 MemoryStore.find_path）
    return memory.find_path(
        args.get("source_id", ""),
        args.get("target_id", ""),
        max_hops=args.get("max_hops", 6),
    )


def _recall(memory: Any, args: dict) -> str:
    return memory.recall(args.get("limit", 5))


def _timeline(memory: Any, args: dict) -> str:
    return memory.timeline(
        args.get("universe", REALITY_UNIVERSE),
        args.get("limit", 0),
    )


def _generalize(memory: Any, args: dict) -> str:
    return memory.generalize(args.get("node_ids", []), args.get("focus"))


def _arbitrate(memory: Any, args: dict) -> str:
    # events_per_fact 从合并 args 取（支持 ToolsetConfig.params 覆盖）；缺省 3（同 MemoryStore.arbitrate）
    # 注意：本工具内部 purpose=adjudicate，与查询管线的 arbitrate purpose 无关（design D9）
    return memory.arbitrate(
        args.get("node_ids", []),
        args.get("question", ""),
        events_per_fact=args.get("events_per_fact", 3),
    )


def _split(memory: Any, args: dict) -> str:
    return memory.split_concept(args.get("node_id", ""), args.get("focus"))


def _merge(memory: Any, args: dict) -> str:
    return memory.merge_concepts(args.get("node_ids", []), args.get("focus"))


def _get_cross_universe_edges(memory: Any, args: dict) -> str:
    return memory.get_cross_universe_edges(args.get("node_id", ""), args.get("limit", 50))


def _link_cross_universe(memory: Any, args: dict) -> str:
    return memory.link_cross_universe(args.get("source_id", ""), args.get("target_id", ""))


@dataclass
class ToolSpec:
    """单个工具：对 LLM 暴露的 schema + 分发到 MemoryStore 原语的纯 handler。

    Args:
        name: 工具名（LLM 经 tool calling 引用；也是 dispatch_table / ToolsetConfig
            的 key——故 ToolsetConfig.params 按工具名索引，非原语名）。
        schema: openai function tool schema（``{"type": "function", "function": {...}}``）。
        handler: ``(memory, args) -> str`` 纯函数；trace / 异常隔离由 ``MemoryAgent._dispatch`` 负责。
        readonly: 该工具是否只读（不改图）。``learn``=False（唯一写图工具）；其余 6 个默认
            True。只读召回（``/recall``）经 ``READONLY_TOOL_NAMES`` 按 ``readonly`` 取白名单——
            **新增写图工具 MUST 标 ``readonly=False``**，否则会被静默放进只读召回、破坏
            "召回 MUST NOT 写图"（白名单而非 ``if name != "learn"`` 黑名单，避免漏维护）。
    """

    name: str
    schema: dict
    handler: Callable[[Any, dict], str]
    readonly: bool = True


BUILTIN_TOOLS: dict[str, ToolSpec] = {
    "learn": ToolSpec(
        name="learn",
        schema={
            "type": "function",
            "function": {
                "name": "learn",
                "description": (
                    "把一段信息写入记忆图谱（复用 MCS 写管线，自动抽概念入图）。"
                    "仅当用户明确要求记住时调用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "要记住的文本",
                        }
                    },
                    "required": ["text"],
                },
            },
        },
        handler=_learn,
        readonly=False,  # learn 是唯一写图工具——禁出于只读召回（/recall）
    ),
    "search": ToolSpec(
        name="search",
        schema={
            "type": "function",
            "function": {
                "name": "search",
                "description": (
                    "搜索记忆图谱的种子节点作为导航入口，返回节点列表（含 id）。"
                    "mode=keyword 按用户输入做关键词/字面匹配（主力，已实现）；"
                    "mode=direct 返回顶层 hub 节点（无明确关键词时用，已实现）；"
                    "mode=vector 向量检索（未实现，勿用）。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "查询内容（自然语言）",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["keyword", "direct", "vector"],
                            "description": "搜索模式，默认 keyword",
                        },
                        "universe": {
                            "type": "string",
                            "description": "查询限定哪个 universe（世界），默认 __reality__（现实）",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        handler=_search,
    ),
    "associate": ToolSpec(
        name="associate",
        schema={
            "type": "function",
            "function": {
                "name": "associate",
                "description": (
                    "查看种子节点的一跳邻居（关联/互斥端点，含 id），零成本、即时返回；"
                    "多跳探索靠对邻居 id 继续 associate（每步可控）。"
                    # mode=mcs（框架全管线 BFS）不进 enum：LLM 可见即会被选用、成本
                    # 一次≈15 次内部 LLM 调用（LoCoMo v5 实测）；显式调用方经
                    # ToolsetConfig.params / 代码路径仍可用。
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "seed_id": {
                            "type": "string",
                            "description": "种子节点 id（由 search 返回的 [id:...]）",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "邻居显示上限，默认 60",
                        },
                    },
                    "required": ["seed_id"],
                },
            },
        },
        handler=_associate,
    ),
    "reason": ToolSpec(
        name="reason",
        schema={
            "type": "function",
            "function": {
                "name": "reason",
                "description": (
                    "在两个已知节点间找连通路径（双向最短路径，允许失败）。"
                    "source_id/target_id 由前序工具返回的 [id:...] 提供。找不到则告知无路径。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_id": {
                            "type": "string",
                            "description": "起点节点 id",
                        },
                        "target_id": {
                            "type": "string",
                            "description": "终点节点 id",
                        },
                    },
                    "required": ["source_id", "target_id"],
                },
            },
        },
        handler=_reason,
    ),
    "recall": ToolSpec(
        name="recall",
        schema={
            "type": "function",
            "function": {
                "name": "recall",
                "description": (
                    "回忆最近发生的事件（按时间倒排，纯近期口径）。"
                    "用于回答「我最近记了什么 / 最近有什么」这类时间相关问题；"
                    "返回结果受 limit 条数与上下文预算双约束。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "返回事件数上限，默认 5",
                        }
                    },
                    "required": [],
                },
            },
        },
        handler=_recall,
    ),
    "timeline": ToolSpec(
        name="timeline",
        schema={
            "type": "function",
            "function": {
                "name": "timeline",
                "description": (
                    "组装某 universe（世界）的叙事时间线：取该世界事件层的事件、"
                    "按时间**升序**返回（查询期组装的虚拟视图，不改图）。"
                    "用于「这部作品的时间线 / 事件先后顺序」类问题。"
                    "作品世界传作品名（如 三国演义）；查现实事件时间线传 __reality__。"
                    "作品纪年按数字年排序（\"建安五年\"等混合纪年暂排末尾）；"
                    "与 recall（现实近期倒排）互补，不要混用。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "universe": {
                            "type": "string",
                            "description": "时间线所属世界：作品名或 __reality__",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回事件数上限（0=不限，仍受上下文预算约束）",
                        },
                    },
                    "required": ["universe"],
                },
            },
        },
        handler=_timeline,
    ),
    "generalize": ToolSpec(
        name="generalize",
        schema={
            "type": "function",
            "function": {
                "name": "generalize",
                "description": (
                    "概括若干节点的公共上位概念 / 共性（只读语义判断，不改图）。"
                    "用于理解一组相关概念的关系。node_ids 由前序工具（search/associate）"
                    "返回的 [id:...] 提供。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要概括的节点 id 列表",
                        },
                        "focus": {
                            "type": "string",
                            "description": "可选聚焦语境，引导概括方向",
                        },
                    },
                    "required": ["node_ids"],
                },
            },
        },
        handler=_generalize,
    ),
    "arbitrate": ToolSpec(
        name="arbitrate",
        schema={
            "type": "function",
            "function": {
                "name": "arbitrate",
                # 命名消歧（design D9）：本工具内部 purpose=adjudicate，
                # 与查询管线 LLMArbitrationPlugin 的 arbitrate purpose 同名不同域、无关。
                "description": (
                    "对若干互斥事实做仲裁裁决：反查每个事实的背书事件、由 LLM 裁决采信"
                    "哪个事实并给出理由（只读、不改图、不写裁决回图）。"
                    "node_ids 应为事实节点 id，由前序工具返回的 [id:...] 提供。"
                    "（本工具内部 purpose=adjudicate，与查询管线的 arbitrate purpose 无关。）"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "互斥事实节点 id 列表（应为事实节点）",
                        },
                        "question": {
                            "type": "string",
                            "description": "裁决的问题 / 语境",
                        },
                    },
                    "required": ["node_ids", "question"],
                },
            },
        },
        handler=_arbitrate,
    ),
    "split": ToolSpec(
        name="split",
        schema={
            "type": "function",
            "function": {
                "name": "split",
                "description": (
                    "拆分一个粒度耦合的概念节点为多个独立节点（写图）。"
                    "用于节点 content 把【一个类别和某特化】耦合（如'按摩'实讲泰式特点），"
                    "或【多个独立实体】被误并为一个（如'小明和小红'）。"
                    "node_id 由前序工具（search/associate）返回的 [id:...] 提供。"
                    "**不该调**：content 自洽别拆、描述不准是重写不是拆、拿不准别拆（错拆制造噪音）。"
                    "返回的产物 id 是守门前快照——拆后守门可能重组产物，后续引用前请重新 search 定位。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string", "description": "要拆的节点 id"},
                        "focus": {"type": "string", "description": "可选，拆分语境/意图"},
                    },
                    "required": ["node_id"],
                },
            },
        },
        handler=_split,
        readonly=False,
    ),
    "merge": ToolSpec(
        name="merge",
        schema={
            "type": "function",
            "function": {
                "name": "merge",
                "description": (
                    "合并若干本就同一个的节点为一个（写图）——异名/同义/重复建。"
                    "node_ids 由前序工具返回的 [id:...] 提供（≥2）。"
                    "**不该调**：同名异义别合（'苹果'水果vs公司）、互斥禁合、"
                    "mere 相关用关联而非合并、拿不准别合（错合丢身份）。"
                    "core 写入已自动合并同义；本工具用于 agent 发觉残留重复、主动收口。"
                    "返回的 keep id 是守门前快照——合并增扇出可能触发裂变重组，后续引用前请重新 search 定位。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "要合并的节点 id 列表（≥2）",
                        },
                        "focus": {"type": "string", "description": "可选，合并语境"},
                    },
                    "required": ["node_ids"],
                },
            },
        },
        handler=_merge,
        readonly=False,
    ),
    "get_cross_universe_edges": ToolSpec(
        name="get_cross_universe_edges",
        schema={
            "type": "function",
            "function": {
                "name": "get_cross_universe_edges",
                "description": (
                    "定向查某节点的跨 universe 桥（只读，绕载重）：列出对端 universe 不同的"
                    "关联/互斥边。单 universe 查询（search/associate）默认不跨 universe；"
                    "需显式跨查（如确认演义曹操 ↔ 正史曹操 是同一实体的不同世界叙述）时用此工具。"
                    "node_id 由前序工具返回的 [id:...] 提供。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {
                            "type": "string",
                            "description": "要查跨 universe 桥的节点 id",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回边数上限，默认 50",
                        },
                    },
                    "required": ["node_id"],
                },
            },
        },
        handler=_get_cross_universe_edges,
    ),
    "link_cross_universe": ToolSpec(
        name="link_cross_universe",
        schema={
            "type": "function",
            "function": {
                "name": "link_cross_universe",
                "description": (
                    "建跨 universe 概念桥（写图，唯一创建路径）：给两个不同 universe 的节点"
                    "建普通关联边。仅当判定两节点是同一实体的不同世界叙述（如演义曹操 ↔ 正史曹操）"
                    "时调用。护栏：两端 universe 必须不同（同 univ 用既有对齐、勿调本工具）、"
                    "同对去重、不触发合并。建后仅 get_cross_universe_edges 可取回（不进活跃视图）。"
                    "source_id/target_id 由前序工具返回的 [id:...] 提供。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string", "description": "一端节点 id"},
                        "target_id": {"type": "string", "description": "另一端节点 id"},
                    },
                    "required": ["source_id", "target_id"],
                },
            },
        },
        handler=_link_cross_universe,
        readonly=False,
    ),
}


# 只读工具白名单：由 ``ToolSpec.readonly`` 元数据驱动（非 ``if name != "learn"`` 黑名单）。
# 新增写图工具标 ``readonly=False`` 即自动排除出只读召回——避免黑名单漏维护、静默破坏
# "召回 MUST NOT 写图"（详见 memory-management-ui spec「召回块」）。
READONLY_TOOL_NAMES: tuple[str, ...] = tuple(
    name for name, spec in BUILTIN_TOOLS.items() if spec.readonly
)


@dataclass
class ToolsetConfig:
    """工具集配置：启用子集 + 按工具名覆盖参数。

    Attributes:
        enabled: 启用的工具名列表；None = 全部 12 个内置。含未知名时该名被忽略
            （不暴露 schema，LLM 调它 → ``[error] 未知工具``）。
        params: 按工具名（非原语名）覆盖参数；合并口径 ``handler(memory, {**llm_args, **params})``
            ——``params`` 覆盖 LLM 同名入参。如 ``{"reason": {"max_hops": 8}}``
            或 ``{"arbitrate": {"events_per_fact": 3}}``。
    """

    enabled: list[str] | None = None
    params: dict[str, dict] = field(default_factory=dict)


def build_toolset(
    registry: dict[str, ToolSpec],
    config: ToolsetConfig | None = None,
) -> tuple[list[dict], dict[str, tuple[Callable[[Any, dict], str], dict]]]:
    """按 ``ToolsetConfig`` 过滤注册表，产 ``(schemas_for_llm, dispatch_table)``。

    - ``enabled=None`` → 全部工具；否则仅含 enabled 列出的**已知**工具名（未知名跳过、
      不暴露 schema）。
    - ``dispatch_table[name] = (handler, params)``；``params = config.params.get(name, {})``，
      供 ``MemoryAgent._dispatch`` 合并 ``handler(memory, {**llm_args, **params})``（params 覆盖同名入参）。
    """
    cfg = config or ToolsetConfig()
    names = list(registry.keys()) if cfg.enabled is None else list(cfg.enabled)
    schemas: list[dict] = []
    dispatch: dict[str, tuple[Callable[[Any, dict], str], dict]] = {}
    for name in names:
        spec = registry.get(name)
        if spec is None:
            continue  # enabled 含未知工具名：跳过（schema 不暴露、dispatch 缺省→未知工具 error）
        schemas.append(spec.schema)
        dispatch[name] = (spec.handler, dict(cfg.params.get(name, {})))
    return schemas, dispatch


# 已废弃别名：= 全 12 内置 schemas（保外部 ``from ... import MEMORY_TOOLS`` 不断裂）。
# 逻辑已由 BUILTIN_TOOLS + build_toolset 取代；后续 change 移除。
MEMORY_TOOLS: list[dict] = [spec.schema for spec in BUILTIN_TOOLS.values()]
