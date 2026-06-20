"""写入管道 - 将文本导入 MCS 的 7 阶段管道。

7 个阶段按顺序执行，参见 openspec/specs/write-pipeline/spec.md：

    ① 前置插件链         (PostprocessPlugin chain on text)
    ② 关联节点定位       (复用查询管道)
    ③ 概念提取           (LLM: extract_concepts)
    ④ 关系判定           (LLM: judge_relations → DecisionList)
    ⑤ 图更新             (无 LLM；原子地应用 DecisionList)
    ⑥ 压缩判定插件链     (CompactionPlugin chain, 条件性, 含不变量守门)
    ⑦ 自动落盘           (SQLiteStore 增量持久化)

阶段 ④ 产生一个 ``DecisionList``（纯数据）；阶段 ⑤ 应用它。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mcs.core.errors import InvalidDecisionError, UnknownActionError
from mcs.entities.decisions import ConceptDraft, Decision, DecisionList
from mcs.entities.graph import CLASS_CONCEPT, EDGE_ASSOC

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginManager
    from mcs.core.query_engine import QueryEngine
    from mcs.core.store import StoreInterface
    from mcs.core.token_budget import TokenBudget
    from mcs.entities.config import MCSConfig
    from mcs.entities.graph import Node
    from mcs.interfaces.llm import LLMInterface


logger = logging.getLogger(__name__)


@dataclass
class WriteContext:
    """贯穿一次 ingest() 调用的状态。

    规范中的 8 个生命周期字段，加上自由元数据：

    - ``system_prompt``: 不变量
    - ``user_input``: 原始文本，不变量
    - ``processed``: 阶段 ① 预处理的输出
    - ``related``: 阶段 ② 的输出（来自复用的查询管道）
    - ``concepts``: 阶段 ③ 的输出
    - ``decisions``: 阶段 ④ 的输出
    - ``changed``: 阶段 ⑤ 的输出（新创建或合并的节点）
    - ``persisted``: 阶段 ⑦ 的输出（落盘是否成功）

    参见 openspec/specs/write-pipeline/spec.md "WriteContext 含八个状态字段"。
    """

    system_prompt: str = ""
    user_input: str = ""
    processed: str = ""
    related: list[Node] = field(default_factory=list)
    concepts: list[ConceptDraft] = field(default_factory=list)
    decisions: DecisionList = field(default_factory=list)
    changed: list[Node] = field(default_factory=list)
    persisted: bool = False
    metadata: dict = field(default_factory=dict)


class WritePipeline:
    """写入管道协调器。

    持有以下引用：
      - graph（用于阶段 ⑤ 更新）
      - llm（用于阶段 ③ ④ LLM 调用；也用于 ⑥ 压缩的 llm_caller）
      - query_engine（用于阶段 ② 复用）
      - plugin_manager（用于解析预处理和压缩链）
    """

    def __init__(
        self,
        store: StoreInterface,
        llm: LLMInterface,
        query_engine: QueryEngine,
        plugin_manager: PluginManager,
        token_budget: TokenBudget,
        config: MCSConfig | None = None,
        system_prompt: str = "",
    ):
        self.store = store
        self.llm = llm
        self.query_engine = query_engine
        self.plugin_manager = plugin_manager
        self.token_budget = token_budget
        self.config = config
        self.system_prompt = system_prompt
        # merge 后 content 超此阈值触发 LLM 压缩（0 = 禁用）
        cfg_dict = config.model_dump() if config and hasattr(config, "model_dump") else {}
        self.merge_content_threshold: int = int(
            cfg_dict.get("merge_content_threshold", 500)
        )

    # === 公共 API ===

    def ingest(self, text: str, **metadata: Any) -> WriteContext:
        """执行 7 阶段写入管道。返回最终的 WriteContext。

        概念提取为空时静默返回（跳过阶段 ④⑤⑥⑦）。
        """
        ctx = WriteContext(
            system_prompt=self.system_prompt,
            user_input=text,
            metadata=dict(metadata),
        )

        # 阶段 ①: 前置插件链（幂等检查/摘要等）
        processed = self._run_preprocess(text, ctx)
        ctx.processed = processed

        # 阶段 ②: 关联节点定位（轻量查询模式）
        ctx.related = self.query_engine.query_nodes(processed)

        # 阶段 ③: 概念提取
        concepts = self.llm.call(
            purpose="extract_concepts",
            nodes_in=ctx.related,
            free_args={"text": processed},
        ) or []
        ctx.concepts = concepts
        if not concepts:
            self._mark_ingested_if_success(ctx)
            return ctx  # 概念数为 0 时静默返回（仍标记已摄入，避免续跑重复处理空块）

        # 阶段 ④: 关系判定
        decisions = self.llm.call(
            purpose="judge_relations",
            nodes_in=ctx.related,
            free_args={"concepts": _format_concepts(concepts)},
        ) or []
        # 重新附加完整的 ConceptDraft 对象（解析器只知道名称）
        _reattach_concepts(decisions, concepts)
        # 丢弃结构上无法应用的坏决策（LLM 偶发 target_id=null），避免整次摄入失败
        decisions = self._sanitize_decisions(decisions)
        ctx.decisions = decisions

        # 阶段 ⑤: 图更新
        ctx.changed = self._apply_decisions(decisions)
        self._attach_pending_source(ctx)
        self._notify_indexes(ctx.changed)

        # 阶段 ⑥: 压缩判定插件链（含不变量守门）
        self._run_compaction(ctx.changed)

        # 阶段 ⑦: 自动落盘
        self._run_persist(ctx)

        # 成功完成 → 标记本块已摄入（mark-on-success，与节点提交时机一致）
        self._mark_ingested_if_success(ctx)

        return ctx

    def _mark_ingested_if_success(self, ctx: WriteContext) -> None:
        """成功完成后把本块记入 idempotency 标记（mark-on-success）。

        - 有变更节点但未成功落盘（持久化失败/中断）→ **不标记**，留待续跑重试；
        - 其余正常完成（落盘成功，或本就无节点可落盘）→ 标记。

        无 ``_pending_source``（未启用 idempotency 或无文档上下文）时为 no-op。
        通过 duck-typed ``record_ingested`` 调用，避免 core 硬编码具体插件名。
        """
        source = ctx.metadata.get("_pending_source")
        if source is None:
            return
        if ctx.changed and not ctx.persisted:
            return  # 有节点却未落盘成功 → 不标记，下次续跑重试该块

        from mcs.core.plugin import PluginType

        for plugin in self.plugin_manager.get_all(PluginType.WRITE_PREPROCESS):
            recorder = getattr(plugin, "record_ingested", None)
            if callable(recorder):
                recorder(source.doc_id, source.chunk_id, source.content_hash)

    def _attach_pending_source(self, ctx: WriteContext) -> None:
        """把 IdempotencyCheckPlugin 暂存于 ``ctx.metadata`` 的 Source 挂到本次
        新建/合并的节点上，填充 ``extensions["source_tracking"]["sources"]``。

        无 ``_pending_source`` 时为 no-op（未启用 source_tracking 时不受影响）。
        """
        source = ctx.metadata.get("_pending_source")
        if source is None:
            return
        for node in ctx.changed:
            slot = node.extensions.setdefault("source_tracking", {"sources": []})
            slot.setdefault("sources", []).append(source)

    def _notify_indexes(self, changed_nodes: list[Node]) -> None:
        """通知每个 IndexInterface 插件已更改的节点，以保持索引同步。
        替代旧的 ``on_created_or_merged`` 管道钩子的角色。
        """
        from mcs.core.plugin import PluginType

        indexes = self.plugin_manager.get_all(PluginType.INDEX)
        for index in indexes:
            for node in changed_nodes:
                try:
                    index.update_entry(node)
                except NotImplementedError:
                    continue

    # === 阶段辅助方法 ===

    def _run_preprocess(self, text: str, ctx: WriteContext) -> str:
        """阶段 ①：串行 WritePreprocessPlugin 链。"""
        from mcs.core.plugin import PluginType

        plugins = self.plugin_manager.get_all(PluginType.WRITE_PREPROCESS)
        result: Any = text
        for plugin in plugins:
            result = plugin.preprocess(result, ctx)
        return result if isinstance(result, str) else text

    def _sanitize_decisions(self, decisions: DecisionList) -> DecisionList:
        """丢弃结构上无法应用的 LLM 决策，避免单个坏决策使整次摄入失败。

        merge 缺 target_id（LLM 偶尔返回 null）→ 丢弃并告警；
        其余仍交由 ``_apply_decisions`` 严格处理。
        """
        cleaned: DecisionList = []
        for d in decisions:
            if d.action == "merge" and not d.target_id:
                logger.warning(
                    "Dropping %s decision without target_id (concept=%r)",
                    d.action,
                    getattr(d.concept, "name", None),
                )
                continue
            cleaned.append(d)
        return cleaned

    def _apply_decisions(self, decisions: DecisionList) -> list[Node]:
        """阶段 ⑤：将每个 Decision 分派到原子 GraphStore 操作。

        返回新创建或合并的节点列表（即状态发生变化的节点）。

        两遍处理：第一遍派发 3 种 action 并记录「概念名 → 节点 id」映射；第二遍把
        ``edges_to_names``（同一批新概念之间的篇内关系）按名解析成边——兄弟概念此刻
        已全部建好，弥补"同次摄入的概念之间无法用 id 互连"的缺口。
        """

        changed: list[Node] = []
        name_to_id: dict[str, str] = {}
        pending_named_edges: list[tuple[str, list[dict]]] = []
        # 精确同名去重索引：create 时若已有同名节点则并入而非新建（确定性兜底，
        # 不依赖 judge_relations 的 merge 判定——其 prompt 偏向 create 会让同名实体
        # 裂成多个节点、碎片化事实、压低召回）。
        existing_by_name: dict[str, str] = {}
        for n in self.store.get_all_nodes():
            key = _norm_name(n.name)
            if key:
                existing_by_name.setdefault(key, n.id)
        for decision in decisions:
            action = decision.action
            cname = decision.concept.name if decision.concept else None
            if action == "merge":
                if decision.target_id is None:
                    raise InvalidDecisionError("merge without target_id")
                self._dispatch_merge(decision)
                node = self.store.get_node(decision.target_id)
                if node is not None:
                    changed.append(node)
                if cname:
                    name_to_id[cname] = decision.target_id
            elif action == "create":
                dup_id = existing_by_name.get(_norm_name(cname)) if cname else None
                if dup_id is not None and self.store.get_node(dup_id) is not None:
                    # 同名已存在 → 并入既有节点（content/别名/edges_to），不新建
                    node = self._merge_concept_into(dup_id, decision)
                    changed.append(node)
                    if cname:
                        name_to_id[cname] = dup_id
                    if decision.edges_to_names:
                        pending_named_edges.append((dup_id, decision.edges_to_names))
                else:
                    node = self._dispatch_create(decision)
                    changed.append(node)
                    if cname:
                        name_to_id[cname] = node.id
                        key = _norm_name(cname)
                        if key:
                            existing_by_name.setdefault(key, node.id)  # 同批后续同名也并入
                    if decision.edges_to_names:
                        pending_named_edges.append((node.id, decision.edges_to_names))
            elif action == "no_op":
                continue  # 显式无操作；无需处理
            else:
                raise UnknownActionError(action)

        # 第二遍：篇内关系边（统一模型：关联边，无 label；谓词落点由事实节点承载，
        # 留待写入管线 Phase C #30 实现。当前篇内概念间关联以 关联 边直连。）
        for source_id, edge_specs in pending_named_edges:
            for edge_info in edge_specs:
                target_name = edge_info.get("target_name", "")
                target_id = name_to_id.get(target_name)
                if target_id:
                    self.store.add_edge(source_id, target_id, type=EDGE_ASSOC)
        return changed

    def _dispatch_merge(self, decision: Decision) -> None:
        """合并：把新概念的名称/别名并入 ``target_id`` 的别名槽，并把
        concept content 追加到目标节点的 content（子串去重）。

        直接 mutate ``node.extensions`` / ``node.content``；
        写完后 ``_notify_indexes`` 会重新索引该节点。
        """
        node = self.store.get_node(decision.target_id)  # type: ignore[arg-type]
        if node is None:
            return
        # 1) 别名并入 extensions["alias_index"]["aliases"]（AliasIndexPlugin 读取的槽）
        aliases_to_add = list(decision.aliases_to_add)
        if decision.concept and decision.concept.name:
            aliases_to_add.append(decision.concept.name)
        if aliases_to_add:
            slot = node.extensions.setdefault("alias_index", {"aliases": []})
            existing = slot.setdefault("aliases", [])
            for alias in aliases_to_add:
                if alias and alias != node.name and alias not in existing:
                    existing.append(alias)
        # 2) concept content 追加到目标节点 content（子串去重）
        if decision.concept and decision.concept.content:
            incoming = decision.concept.content.strip()
            existing_content = (node.content or "").strip()
            if incoming and incoming not in existing_content:
                node.content = f"{existing_content}\n{incoming}" if existing_content else incoming
        # 3) content 压缩：追加后超阈值时调用 LLM 压缩，防止单节点 content 无界增长
        if (
            self.merge_content_threshold > 0
            and len(node.content or "") > self.merge_content_threshold
        ):
            try:
                compressed = self.llm.call(
                    purpose="gen_summary",
                    nodes_in=[node],
                    free_args={"max_tokens": 200},
                )
                if isinstance(compressed, str) and compressed.strip():
                    node.content = compressed.strip()
            except Exception:
                logger.warning(
                    "merge content 压缩失败，保留原始 content (node=%s)",
                    node.id,
                    exc_info=True,
                )

    def _dispatch_create(self, decision: Decision) -> Node:
        """创建：新节点 + 到 ``edges_to`` 中每个锚点的关联边。

        统一模型下概念间关联为 ``关联`` 边（无 label；开放谓词落事实节点 content，
        事实节点化留待写入管线 Phase C #30）。
        """
        from mcs.entities.graph import Node

        c = decision.concept
        if c is None:
            raise InvalidDecisionError("create without concept payload")
        node = Node(
            id=str(uuid.uuid4()),
            name=c.name,
            content=c.content,
            node_class=CLASS_CONCEPT,
        )
        self.store.add_node(node)
        for edge_info in decision.edges_to or []:
            anchor_id = edge_info.get("target_id", edge_info) if isinstance(edge_info, dict) else edge_info
            self.store.add_edge(node.id, anchor_id, type=EDGE_ASSOC)
        return node

    def _merge_concept_into(self, existing_id: str, decision: Decision) -> Node:
        """同名去重：把本应 create 的概念并入既有同名节点，返回既有节点。

        复用 ``_dispatch_merge`` 合 content/别名，再把该概念的 ``edges_to`` 锚点边
        挂到既有节点（create 的 edges_to 不能丢）。
        """
        self._dispatch_merge(
            Decision(
                action="merge",
                concept=decision.concept,
                target_id=existing_id,
                aliases_to_add=decision.aliases_to_add,
            )
        )
        for edge_info in decision.edges_to or []:
            anchor_id = edge_info.get("target_id", edge_info) if isinstance(edge_info, dict) else edge_info
            self.store.add_edge(existing_id, anchor_id, type=EDGE_ASSOC)
        return self.store.get_node(existing_id)

    def _run_compaction(self, changed_nodes: list[Node]) -> None:
        """阶段 ⑥：每个 CompactionPlugin 检查 should_run，然后运行。"""
        from mcs.core.plugin import PluginType

        plugins = self.plugin_manager.get_all(PluginType.COMPACTION)
        for plugin in plugins:
            if plugin.should_run(changed_nodes, self.store):
                plugin.run(changed_nodes, self.store, self.llm.call)

    def _run_persist(self, ctx: WriteContext) -> None:
        """阶段 ⑦：把本次 ingest 的全部图变更增量落盘（节点 + 边 + 删除）。

        变更由 SQLiteStore 在每次 add/update/delete 时跟踪——涵盖阶段⑤的决策与阶段⑥
        压缩/裂变对**虚拟根、hub、层级边**的增删改（含重挂导致的边删除），经
        ``flush_changes`` 一次提交。决策对既有节点的原地改动（statements / 别名 /
        source_tracking）不经 store 方法，故对 ``ctx.changed`` 显式 ``mark_node_dirty``
        补标。无 SQLiteStore 或 auto_persist 关闭时跳过；异常不影响 ingest 返回。
        """
        auto_persist = getattr(self.config, "auto_persist", True) if self.config else True
        if not auto_persist:
            return

        # 仅 SQLiteStore 支持增量持久化
        from mcs.stores.sqlite_store import SQLiteStore

        if not isinstance(self.store, SQLiteStore) or self.store.conn is None:
            return

        try:
            for node in ctx.changed:
                self.store.mark_node_dirty(node.id)
            self.store.flush_changes()
            ctx.persisted = True
        except Exception:
            logger.warning("Auto-persist failed", exc_info=True)


# === 辅助函数 ===


def _format_concepts(concepts: list[ConceptDraft]) -> str:
    """ConceptDraft 的紧凑字符串表示，用于 ``judge_relations`` LLM 提示的
    ``{concepts}`` 占位符。
    """
    lines = []
    for i, c in enumerate(concepts, 1):
        lines.append(f"{i}. {c.name}: {c.content}")
        for hint in c.relation_hints:
            lines.append(f"   - {hint}")
    return "\n".join(lines) if lines else "(无)"


def _reattach_concepts(
    decisions: DecisionList, concepts: list[ConceptDraft]
) -> None:
    """judge_relations 解析器只携带 concept_name；此辅助函数从 extract_concepts
    输出中交换完整的 ConceptDraft 对象。
    """
    by_name = {c.name: c for c in concepts}
    for d in decisions:
        if d.concept is not None and d.concept.name in by_name:
            d.concept = by_name[d.concept.name]


def _norm_name(name: str | None) -> str:
    """概念名归一化（去空白 + 小写），用于精确同名去重。"""
    return (name or "").strip().lower()
