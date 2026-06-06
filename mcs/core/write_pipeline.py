"""写入管道 - 将文本导入 MCS 的 7 阶段管道。

7 个阶段按顺序执行，参见 openspec/specs/write-pipeline/spec.md：

    ① 前置插件链         (PostprocessPlugin chain on text)
    ② 关联节点定位       (复用查询管道)
    ③ 概念提取           (LLM: extract_concepts)
    ④ 关系判定           (LLM: judge_relations → DecisionList)
    ⑤ 图更新             (无 LLM；原子地应用 DecisionList)
    ⑥ 压缩判定插件链     (CompactionPlugin chain, 条件性)
    ⑦ 自动落盘           (StorageInterface 增量持久化)

阶段 ④ 产生一个 ``DecisionList``（纯数据）；阶段 ⑤ 应用它。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mcs.core.decisions import ConceptDraft, Decision, DecisionList
from mcs.core.errors import InvalidDecisionError, UnknownActionError

if TYPE_CHECKING:
    from mcs.core.config import MCSConfig
    from mcs.core.graph import GraphStoreInterface, Node
    from mcs.core.plugin_manager import PluginManager
    from mcs.core.query_engine import QueryEngine
    from mcs.core.token_budget import TokenBudget
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
    skip: bool = False


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
        graph: GraphStoreInterface,
        llm: LLMInterface,
        query_engine: QueryEngine,
        plugin_manager: PluginManager,
        token_budget: TokenBudget,
        config: MCSConfig | None = None,
        system_prompt: str = "",
    ):
        self.graph = graph
        self.llm = llm
        self.query_engine = query_engine
        self.plugin_manager = plugin_manager
        self.token_budget = token_budget
        self.config = config
        self.system_prompt = system_prompt

    # === 公共 API ===

    def ingest(self, text: str, **metadata: Any) -> WriteContext:
        """执行 7 阶段写入管道。返回最终的 WriteContext。

        概念提取为空时静默返回（跳过阶段 ④⑤⑥⑦）；
        通过 ``ctx.skip = True`` 的幂等跳过也会短路。
        """
        ctx = WriteContext(
            system_prompt=self.system_prompt,
            user_input=text,
            metadata=dict(metadata),
        )

        # 阶段 ①: 前置插件链（幂等检查/摘要等）
        processed = self._run_preprocess(text, ctx)
        if ctx.skip:
            return ctx
        ctx.processed = processed

        # 阶段 ②: 关联节点定位（复用查询管道）
        related = self.query_engine.query(processed)
        ctx.related = related if isinstance(related, list) else []

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

        # 阶段 ⑤.5: 立即守门检查（不变量保证）
        self._guard_invariant(ctx.changed)

        # 阶段 ⑥: 压缩判定插件链
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

        for plugin in self.plugin_manager.get_all(PluginType.POSTPROCESS):
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
        """阶段 ①：串行 PostprocessPlugin 链，``position == 'write_preprocess'``。"""
        from mcs.core.plugin import PluginType

        plugins = [
            p
            for p in self.plugin_manager.get_all(PluginType.POSTPROCESS)
            if getattr(p, "position", "query_postprocess") == "write_preprocess"
        ]
        result: Any = text
        for plugin in plugins:
            result = plugin.process(result, ctx)
            if ctx.skip:
                return result if isinstance(result, str) else text
        return result if isinstance(result, str) else text

    def _sanitize_decisions(self, decisions: DecisionList) -> DecisionList:
        """丢弃结构上无法应用的 LLM 决策，避免单个坏决策使整次摄入失败。

        merge / attach_statement 缺 target_id（LLM 偶尔返回 null）→ 丢弃并告警；
        其余仍交由 ``_apply_decisions`` 严格处理，保持内部不变量与既有契约。
        """
        cleaned: DecisionList = []
        for d in decisions:
            if d.action in ("merge", "attach_statement") and not d.target_id:
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

        两遍处理：第一遍派发 4 种 action 并记录「概念名 → 节点 id」映射；第二遍把
        ``edges_to_names``（同一批新概念之间的篇内关系）按名解析成边——兄弟概念此刻
        已全部建好，弥补"同次摄入的概念之间无法用 id 互连"的缺口。
        """

        changed: list[Node] = []
        name_to_id: dict[str, str] = {}
        pending_named_edges: list[tuple[str, list[str]]] = []
        for decision in decisions:
            action = decision.action
            cname = decision.concept.name if decision.concept else None
            if action == "merge":
                if decision.target_id is None:
                    raise InvalidDecisionError("merge without target_id")
                self._dispatch_merge(decision)
                node = self.graph.get_node(decision.target_id)
                if node is not None:
                    changed.append(node)
                if cname:
                    name_to_id[cname] = decision.target_id
            elif action == "create":
                node = self._dispatch_create(decision)
                changed.append(node)
                if cname:
                    name_to_id[cname] = node.id
                if decision.edges_to_names:
                    pending_named_edges.append((node.id, decision.edges_to_names))
            elif action == "attach_statement":
                if decision.target_id is None:
                    raise InvalidDecisionError("attach_statement without target_id")
                self._dispatch_attach(decision)
                node = self.graph.get_node(decision.target_id)
                if node is not None:
                    changed.append(node)
                if cname:
                    name_to_id[cname] = decision.target_id
            elif action == "no_op":
                continue  # 显式无操作；无需处理
            else:
                raise UnknownActionError(action)

        # 第二遍：篇内关系边（add_edge 自带去重 / 防自环 / 端点存在校验）
        for source_id, names in pending_named_edges:
            for nm in names:
                target_id = name_to_id.get(nm)
                if target_id:
                    self.graph.add_edge(source_id, target_id)
        return changed

    def _dispatch_merge(self, decision: Decision) -> None:
        """合并：把新概念的名称/别名并入 ``target_id`` 的别名槽，并把
        ``initial_statements`` 追加到目标的 statements 槽。

        直接 mutate ``node.extensions``（与 ``_dispatch_create`` /
        ``_dispatch_attach`` 同风格）；写完后 ``_notify_indexes`` 会重新索引
        该节点，使新别名立即可被 AliasEntry 查到。
        """
        node = self.graph.get_node(decision.target_id)  # type: ignore[arg-type]
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
        # 2) initial_statements 追加到 statements 槽
        if decision.initial_statements:
            sslot = node.extensions.setdefault("statements", {"items": []})
            sslot.setdefault("items", []).extend(decision.initial_statements)

    def _dispatch_create(self, decision: Decision) -> Node:
        """创建：新节点 + 到 ``edges_to`` 中每个锚点的边。"""
        from mcs.core.graph import Node

        c = decision.concept
        if c is None:
            raise InvalidDecisionError("create without concept payload")
        node = Node(
            id=str(uuid.uuid4()),
            name=c.name,
            content=c.content,
            role="concept",
        )
        self.graph.add_node(node)
        for anchor_id in decision.edges_to or []:
            self.graph.add_edge(node.id, anchor_id)
        # 初始陈述成为新节点上的附加陈述
        if decision.initial_statements:
            # 第一阶段将陈述保留在 extensions 中；第二阶段将其包装为属性节点
            node.extensions.setdefault("statements", {"items": []})["items"].extend(
                decision.initial_statements
            )
        return node

    def _dispatch_attach(self, decision: Decision) -> None:
        """将陈述附加到属性节点（第一阶段简单列表）。"""
        if not decision.statement:
            return
        node = self.graph.get_node(decision.target_id)  # type: ignore[arg-type]
        if node is None:
            return
        slot = node.extensions.setdefault("statements", {"items": []})
        slot.setdefault("items", []).append(decision.statement)

    def _guard_invariant(self, changed_nodes: list[Node]) -> None:
        """阶段 ⑤.5：立即守门检查，确保不变量不被破坏。

        检查 root 和所有 changed_nodes 的一跳邻域是否 ≤ T。
        如果超预算，立即触发 FanoutReducer 的守门逻辑，
        而非等阶段 ⑥ 的 should_run（后者可能因 floor 阈值跳过）。
        """
        from mcs.core.plugin import PluginType
        from mcs.plugins.phase1.fanout_reducer import FanoutReducerPlugin, SEED_ROOT_ID

        fanout_plugin = None
        for plugin in self.plugin_manager.get_all(PluginType.COMPACTION):
            if isinstance(plugin, FanoutReducerPlugin):
                fanout_plugin = plugin
                break

        if fanout_plugin is None or fanout_plugin.token_budget is None:
            return

        # 收集需检查的节点：root + changed
        nodes_to_check: list[Node] = []
        seen: set[str] = set()
        root = self.graph.get_node(SEED_ROOT_ID)
        if root is not None and root.id not in seen:
            nodes_to_check.append(root)
            seen.add(root.id)
        for n in changed_nodes:
            if n.id not in seen:
                nodes_to_check.append(n)
                seen.add(n.id)

        # 对每个超预算节点立即触发裂变
        for node in nodes_to_check:
            neighbors = self.graph.get_neighbors(node.id)
            if fanout_plugin._exceeds_budget(node, neighbors):
                fanout_plugin._compact_node(node, self.graph, self.llm.call)

    def _run_compaction(self, changed_nodes: list[Node]) -> None:
        """阶段 ⑥：每个 CompactionPlugin 检查 should_run，然后运行。"""
        from mcs.core.plugin import PluginType

        plugins = self.plugin_manager.get_all(PluginType.COMPACTION)
        for plugin in plugins:
            if plugin.should_run(changed_nodes, self.graph):
                plugin.run(changed_nodes, self.graph, self.llm.call)

    def _run_persist(self, ctx: WriteContext) -> None:
        """阶段 ⑦：将 ctx.changed 中的节点及关联边增量持久化到 StorageInterface。

        检查 config.auto_persist 开关；无 StorageInterface 或 changed 为空时跳过。
        存储异常被捕获并记录警告，不影响 ingest 返回。
        """
        from mcs.core.plugin import PluginType

        if not ctx.changed:
            return

        auto_persist = getattr(self.config, "auto_persist", True) if self.config else True
        if not auto_persist:
            return

        storage = self.plugin_manager.get(PluginType.STORAGE)
        if storage is None:
            return

        try:
            changed_ids = {n.id for n in ctx.changed}
            persisted_edges: set[tuple[str, str]] = set()

            for node in ctx.changed:
                storage.save_node(node)

            for node in ctx.changed:
                for neighbor in self.graph.get_neighbors(node.id):
                    edge = self.graph.get_edge(node.id, neighbor.id)
                    if edge is None:
                        continue
                    key = (edge.source_id, edge.target_id)
                    if key in persisted_edges:
                        continue
                    if neighbor.id in changed_ids or node.id in changed_ids:
                        storage.save_edge(edge)
                        persisted_edges.add(key)

            # 每次 ingest 落盘后显式提交：消除"滞后一块 + shutdown 丢最后一块"。
            storage.commit()
            ctx.persisted = True
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Auto-persist failed for %d changed nodes", len(ctx.changed),
                exc_info=True,
            )


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
