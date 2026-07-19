"""写入管道 - 将文本导入 MCS 的 ⓪ + 7 阶段管道。

规则入库前置段 ⓪（不经 LLM）+ 7 段 LLM 核心管线，按顺序执行，参见
openspec/specs/write-pipeline/spec.md：

    ⓪ 规则入库           (建事件节点（整输入、timestamp）+ 可选 source 节点；不经 LLM)
    ① 前置插件链         (WritePreprocessPlugin chain on text)
    ② 关联节点定位       (复用查询管道)
    ③ 概念提取           (LLM: extract_concepts；仅 content)
    ④ 关系判定           (LLM: judge_relations → DecisionList)
    ⑤ 图更新             (无 LLM；原子地应用 DecisionList + 事件/source → 概念/事实 背书连边)
    ⑥ 压缩判定插件链     (CompactionPlugin chain, 条件性, 含不变量守门)
    ⑦ 自动落盘           (SQLiteStore 增量持久化)

阶段 ④ 产生一个 ``DecisionList``（纯数据）；阶段 ⑤ 应用它，并把 ⓪ 建的事件 / source
对本次新建 / 命中的概念 / 事实连 ``关联`` 背书边。即便 content 抽取为零概念 / 事实，
⓪ 建的事件 / source 仍随 ⑦ 落盘（记录行为已发生）。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from mcs.core.content_merge import merge_content
from mcs.core.errors import InvalidDecisionError, UnknownActionError
from mcs.entities.decisions import (
    ConceptDraft,
    Decision,
    DecisionList,
    EventData,
    IngestInput,
    SourceData,
    WorkEventDraft,
)
from mcs.entities.graph import (
    CLASS_CONCEPT,
    CLASS_EVENT,
    CLASS_SOURCE,
    CORE_NODE_CLASSES,
    EDGE_ASSOC,
    EDGE_MUTEX,
    REALITY_UNIVERSE,
    Node,
)

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginManager
    from mcs.core.query_engine import QueryEngine
    from mcs.core.store import StoreInterface
    from mcs.core.token_budget import TokenBudget
    from mcs.entities.config import MCSConfig
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

    规则入库产物（⓪ 段，补充字段，不移除既有字段）：

    - ``event_node``: 本次 ingest 记录的事件节点（落时间轴）
    - ``source_nodes``: 按 ``IngestInput.source`` 规则切分建的 source 节点列表

    作品叙事事件产物（③b/⑤b 段，仅 ``work_id`` 非空时非空）：

    - ``work_events``: 阶段 ③b LLM 抽取的 ``WorkEventDraft`` 列表
    - ``work_event_nodes``: 阶段 ⑤b 建的作品叙事事件节点（``universe=work``、纪年 timestamp）

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
    event_node: Node | None = None
    source_nodes: list[Node] = field(default_factory=list)
    target_universe: str = REALITY_UNIVERSE
    work_events: list[WorkEventDraft] = field(default_factory=list)
    work_event_nodes: list[Node] = field(default_factory=list)


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
        # universe 注册表倒排（alias/name → canonical），惰性构建、增量更新——
        # 避免每次带 work_id 的 ingest 全表扫描找元节点（见 _ensure_universe_index）。
        self._universe_index: dict[str, str] | None = None

    # === 公共 API ===

    def ingest(self, data: str | IngestInput, **metadata: Any) -> WriteContext:
        """执行 ⓪ + 7 阶段写入管道。返回最终的 WriteContext。

        入参接受 ``str | IngestInput``：``str`` 归一化为 ``IngestInput(content=text)``
        （now 时间戳、无 source），既有 ``str`` 调用行为不变（除新增的一条记录事件外）。

        概念提取为空时静默返回（跳过 ④⑤⑥），但 ⓪ 建的事件 / source 仍随 ⑦ 落盘
        （记录行为已发生）。
        """
        # 入口归一化：str → IngestInput
        if isinstance(data, str):
            data = IngestInput(content=data)
        merged_metadata = {**data.metadata, **metadata}

        ctx = WriteContext(
            system_prompt=self.system_prompt,
            user_input=data.content,
            metadata=merged_metadata,
        )

        # universe 归属判定（不经 LLM）：work_id 经注册表规范化为 canonical universe id；
        # 摄入行为事件固定 __reality__，概念 / 事实 / source 归 target_universe。
        ctx.target_universe = self._resolve_universe(data.work_id)

        # 阶段 ⓪: 规则入库（不经 LLM）——建事件节点（整输入、timestamp）+ source 节点。
        #   先建，使其 id 可用于 ⑤ 的背书连边；即便 content 抽取为空仍入库（记录行为已发生）。
        ctx.event_node, ctx.source_nodes = self._rule_ingest(data, ctx.target_universe)

        # ①-⑥ 任一阶段异常（多为 LLM 故障）→ 回滚 ⓪ 建的事件 / source 节点后 re-raise。
        # 否则孤儿事件残留内存并被后续 flush 落盘；调用方（如 Consolidator）重试又会
        # 再建一条同内容事件 → 重复。「记录行为已发生」只适用于成功完成的 ingest。
        try:
            # 阶段 ①: 前置插件链（幂等检查/摘要等）——只作用于 content
            processed = self._run_preprocess(data.content, ctx)
            ctx.processed = processed

            # 阶段 ②: 关联节点定位（轻量查询模式，限 target_universe 内——防跨 world 乱连）
            ctx.related = self.query_engine.query_nodes(
                processed, universe=ctx.target_universe
            )

            # 阶段 ③: 概念提取（LLM，仅 content）
            concepts = self.llm.call(
                purpose="extract_concepts",
                nodes_in=ctx.related,
                free_args={"text": processed},
            ) or []
            ctx.concepts = concepts

            # 阶段 ③b: 作品叙事事件抽取（LLM，仅 work universe 启用）。
            # 宪法铁律精确化：现实摄入事件不经 LLM（⓪ 规则）；作品叙事事件
            # （带作品纪年的叙述发生）经 LLM 抽取、MUST NOT 由规则产生。
            if ctx.target_universe != REALITY_UNIVERSE:
                ctx.work_events = self.llm.call(
                    purpose="extract_work_events",
                    nodes_in=[],
                    free_args={"text": processed, "work_id": ctx.target_universe},
                ) or []

            if not concepts and not ctx.work_events:
                # 概念与作品事件均为 0：跳过 ④⑤⑥，但事件 / source 已在 ⓪ 建好
                # （add_node 自动跟踪），仍随 ⑦ 落盘（记录行为已发生）。
                self._run_persist(ctx)
                self._mark_ingested_if_success(ctx)
                return ctx

            # 阶段 ④: 关系判定（无概念时跳过——作品事件不走关系判定）
            decisions: DecisionList = []
            if concepts:
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

            # 阶段 ⑤: 图更新（含事件 / source → 本次概念 / 事实 背书连边）
            ctx.changed = (
                self._apply_decisions(decisions, ctx.target_universe)
                if decisions else []
            )
            # 阶段 ⑤b: 作品叙事事件建节点（先于背书——新建参与者概念与本次概念
            # 同属产出，摄入事件 / source 对其一并背书、source_tracking 一并挂载）
            if ctx.work_events:
                ctx.changed.extend(self._build_work_event_nodes(ctx))
            self._apply_endorsements(ctx)
            self._attach_pending_source(ctx)
            self._notify_indexes(ctx.changed)

            # 阶段 ⑥: 压缩判定插件链（含不变量守门；作品叙事事件一并过守门）
            self._run_compaction(ctx.changed + ctx.work_event_nodes)
        except Exception:
            self._rollback_rule_ingest(ctx)
            raise

        # 阶段 ⑦: 自动落盘
        self._run_persist(ctx)

        # 成功完成 → 标记本块已摄入（mark-on-success，与节点提交时机一致）
        self._mark_ingested_if_success(ctx)

        return ctx

    def run_compaction(self, changed_nodes: list[Node]) -> None:
        """public 守门入口：等价于阶段⑥ ``_run_compaction``——对 ``changed_nodes`` 跑
        CompactionPlugin 链、对层级视图超 T 的节点强制裂变兜底（保核心不变量）。

        供外部图手术（如 agent 层 ``split`` / ``merge`` 工具）改图后过守门；**不重跑
        ①–⑤ / ⑦**、不触碰 ``WriteContext``。ingest 阶段⑥仍直接调 ``_run_compaction``，
        本方法仅暴露同名 public 入口、不改既有逻辑。
        """
        self._run_compaction(changed_nodes)

    def _rollback_rule_ingest(self, ctx: WriteContext) -> None:
        """ingest 中途失败时回滚 ⓪ 建的事件 / source 节点（含其已连的背书边）。

        ``delete_node`` 会一并删除触及该节点的边并进变更跟踪；若节点已被本次
        管线中途的 flush（如查询路径 read-repair 落盘）写入 DB，删除跟踪会在
        下次 flush 时清掉该行——此处再做一次 best-effort flush 使 DB 即刻一致，
        失败不掩盖原始异常（仅告警）。
        """
        # 作品叙事事件一并回滚：事件无同名去重，残留会在调用方重试时重复建
        for node in [ctx.event_node, *ctx.source_nodes, *ctx.work_event_nodes]:
            if node is None:
                continue
            try:
                self.store.delete_node(node.id)
            except Exception:
                logger.warning("回滚事件/source 节点失败: %s", node.id, exc_info=True)
        ctx.event_node = None
        ctx.source_nodes = []
        ctx.work_event_nodes = []
        auto_persist = getattr(self.config, "auto_persist", True) if self.config else True
        flush = getattr(self.store, "flush_changes", None)
        if auto_persist and callable(flush) and getattr(self.store, "conn", None) is not None:
            try:
                flush()
            except Exception:
                logger.warning("回滚后落盘失败（下次 flush 收敛）", exc_info=True)

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

    def _apply_decisions(
        self, decisions: DecisionList, universe: str = REALITY_UNIVERSE
    ) -> list[Node]:
        """阶段 ⑤：将每个 Decision 分派到原子 GraphStore 操作。

        返回新创建或合并的节点列表（即状态发生变化的节点）。

        三遍处理：
        - 第一遍：派发 3 种 action 并记录「概念名 → 节点 id」映射；处理 ``mutex_with``
          （已有事实节点 id → 互斥边）
        - 第二遍：把 ``edges_to_names`` 和 ``mutex_with_names``（同一批新概念之间
          的篇内关系/互斥）按名解析成边——兄弟概念此刻已全部建好

        ``universe`` 贯穿：新建节点注入、同名去重 / 合并 / 互斥均限同 universe
        （跨 universe 不合并、不判互斥——虚构 vs 真实是两个世界、非矛盾）。
        """

        changed: list[Node] = []
        name_to_id: dict[str, str] = {}
        pending_named_edges: list[tuple[str, list[dict]]] = []
        pending_mutex_names: list[tuple[str, list[str]]] = []
        # 精确同名去重索引：create 时若已有同名节点则并入而非新建（确定性兜底，
        # 不依赖 judge_relations 的 merge 判定——其 prompt 偏向 create 会让同名实体
        # 裂成多个节点、碎片化事实、压低召回）。仅纳入**同 universe 核心节点**（概念 /
        # 事实）——跨 universe 同名不并入（演义曹操 ≠ 正史曹操）；事件 / source（⓪
        # 规则入库、名由 content 派生）不是概念，不应吸收概念。
        existing_by_name: dict[str, str] = {}
        for n in self.store.get_all_nodes():
            if n.node_class not in CORE_NODE_CLASSES:
                continue
            if n.universe != universe:  # 同 universe 才参与同名去重
                continue
            key = _norm_name(n.name)
            if key:
                existing_by_name.setdefault(key, n.id)
        for decision in decisions:
            action = decision.action
            cname = decision.concept.name if decision.concept else None
            if action == "merge":
                if decision.target_id is None:
                    raise InvalidDecisionError("merge without target_id")
                self._dispatch_merge(decision, universe)
                node = self.store.get_node(decision.target_id)
                if node is not None:
                    changed.append(node)
                if cname:
                    name_to_id[cname] = decision.target_id
                # merge 事实的互斥边（merge 后新节点继承互斥关系）——限同 universe
                for mid in decision.mutex_with or []:
                    mid_node = self.store.get_node(mid) if mid else None
                    if decision.target_id and mid_node:
                        if mid_node.universe != universe:
                            logger.warning(
                                "跨 universe 互斥被拒绝（%s vs %s），跳过",
                                universe, mid_node.universe,
                            )
                            continue
                        try:
                            self.store.add_edge(decision.target_id, mid, type=EDGE_MUTEX)
                        except ValueError:
                            logger.warning(
                                "互斥边被拒绝（两端非事实）：merge target=%s, mutex_with=%s",
                                decision.target_id, mid,
                            )
            elif action == "create":
                dup_id = existing_by_name.get(_norm_name(cname)) if cname else None
                new_id: str | None = None
                if dup_id is not None and self.store.get_node(dup_id) is not None:
                    # 同名已存在 → 并入既有节点（content/别名/edges_to），不新建
                    node = self._merge_concept_into(dup_id, decision, universe)
                    changed.append(node)
                    new_id = dup_id
                    if cname:
                        name_to_id[cname] = dup_id
                    if decision.edges_to_names:
                        pending_named_edges.append((dup_id, decision.edges_to_names))
                else:
                    node = self._dispatch_create(decision, universe)
                    changed.append(node)
                    new_id = node.id
                    if cname:
                        name_to_id[cname] = node.id
                        key = _norm_name(cname)
                        if key:
                            existing_by_name.setdefault(key, node.id)  # 同批后续同名也并入
                    if decision.edges_to_names:
                        pending_named_edges.append((node.id, decision.edges_to_names))
                # create 事实的互斥边（已有事实 id）——限同 universe
                for mid in decision.mutex_with or []:
                    mid_node = self.store.get_node(mid) if mid else None
                    if new_id and mid_node:
                        if mid_node.universe != universe:
                            logger.warning(
                                "跨 universe 互斥被拒绝（%s vs %s），跳过",
                                universe, mid_node.universe,
                            )
                            continue
                        try:
                            self.store.add_edge(new_id, mid, type=EDGE_MUTEX)
                        except ValueError:
                            logger.warning(
                                "互斥边被拒绝（两端非事实）：source=%s, target=%s",
                                new_id, mid,
                            )
                # 篇内互斥（同批新事实名 → 第二遍解析；同批必同 universe）
                if decision.mutex_with_names:
                    pending_mutex_names.append((new_id or "", decision.mutex_with_names))
            elif action == "no_op":
                continue  # 显式无操作；无需处理
            else:
                raise UnknownActionError(action)

        # 第二遍：篇内关系边（统一模型：关联边，无 label；谓词落点由事实节点承载）
        for source_id, edge_specs in pending_named_edges:
            for edge_info in edge_specs:
                target_name = edge_info.get("target_name", "")
                target_id = name_to_id.get(target_name)
                if target_id:
                    self.store.add_edge(source_id, target_id, type=EDGE_ASSOC)

        # 第二遍：篇内互斥边（事实 ↔ 事实）
        for source_id, mutex_names in pending_mutex_names:
            for target_name in mutex_names:
                target_id = name_to_id.get(target_name)
                if target_id and source_id:
                    try:
                        self.store.add_edge(source_id, target_id, type=EDGE_MUTEX)
                    except ValueError:
                        logger.warning(
                            "篇内互斥边被拒绝（两端非事实）：source=%s, target=%s",
                            source_id, target_id,
                        )

        return changed

    # === 阶段 ⓪ 规则入库原语（事件 / source，不经 LLM）===

    def _resolve_universe(self, work_id: str | None) -> str:
        """``work_id`` → canonical universe id（**不经 LLM**）。

        无 ``work_id`` → :data:`REALITY_UNIVERSE`。有 ``work_id`` → 经 universe 注册表
        （元节点 ``name`` + 别名的字面精确匹配）归一：命中复用其 canonical（= 元节点
        ``name``）；未命中新建 universe 元节点（作品作为现实造物、``universe=__reality__``、
        不持成员）+ 新 canonical（= ``work_id``）。

        **宁裂不并**：纯字面 / 别名精确匹配，MUST NOT 用 LLM / 分词模糊判两 universe
        同世界（误并即污染真值）。canonical id 一旦分配稳定（成员 ``universe`` 标量指向它）。
        """
        if not work_id:
            return REALITY_UNIVERSE
        canonical = self._find_universe_canonical(work_id)
        if canonical is not None:
            return canonical
        self._create_universe_meta_node(work_id)
        return work_id

    def _ensure_universe_index(self) -> dict[str, str]:
        """惰性构建 universe 注册表倒排（``alias/name → canonical``）。

        首次 O(N) 扫全图收集所有 universe 元节点（``extensions["universe_meta"]`` 存在，
        ``node_class=概念``、``universe=__reality__``）的 name + 别名 → canonical(= name)；
        之后 O(1) 查。元节点仅经 :meth:`_create_universe_meta_node` /
        :meth:`register_universe_alias` 改动（均在本类），二者增量更新此缓存，故一致。
        """
        if self._universe_index is None:
            idx: dict[str, str] = {}
            for node in self.store.get_all_nodes():
                meta = (node.extensions or {}).get("universe_meta")
                if not isinstance(meta, dict):
                    continue
                canonical = node.name  # canonical = 元节点 name（首次 work_id 字面）
                idx[node.name] = canonical
                aliases = (node.extensions.get("alias_index", {}) or {}).get(
                    "aliases", []
                )
                for a in aliases or []:
                    idx[a] = canonical
            self._universe_index = idx
        return self._universe_index

    def _find_universe_canonical(self, work_id: str) -> str | None:
        """注册表查询：``work_id`` 匹配已有 universe 元节点（name / 别名精确匹配）则返其
        canonical(= 元节点 name)，否则 None。走惰性倒排缓存（O(1)，见 _ensure_universe_index）。
        """
        return self._ensure_universe_index().get(work_id)

    def _create_universe_meta_node(self, work_id: str) -> Node:
        """新建 universe 元节点（未命中的 canonical universe 的身份锚点）。

        作品作为**现实造物**（真实存在的书 / 影视）→ ``universe=__reality__``、
        ``node_class=概念``；所述世界的成员才 ``universe=<canonical>``。**MUST NOT**
        自动建"成员 → 元节点"归属边（成员靠 ``Node.universe`` 标量归属，防超级 hub）。
        ``content`` 留空（本 change 不抽作品描述，留 ``work-narrative-events``）。
        """
        node = Node(
            id=str(uuid.uuid4()),
            name=work_id,
            content="",
            node_class=CLASS_CONCEPT,
            universe=REALITY_UNIVERSE,  # 作品作为现实造物
            extensions={"universe_meta": {"canonical": work_id}},
        )
        self.store.add_node(node)
        # 通知索引（alias_index 等）——元节点作查询 foothold 需被检索到
        self._notify_indexes([node])
        # 增量更新注册表倒排（缓存已建时）：新 canonical = work_id 字面
        if self._universe_index is not None:
            self._universe_index[work_id] = work_id
        return node

    def register_universe_alias(self, canonical_work_id: str, alias: str) -> bool:
        """把 ``alias`` 登记为 canonical universe 元节点的别名（显式归一治理）。

        用于收"同世界不同写法"碎片（如 "三国" / "Romance…" → "三国演义" 元节点）。
        此后 :meth:`_resolve_universe` 对 ``alias`` 命中复用 canonical（不误裂）。复用
        节点别名设施（``extensions["alias_index"]["aliases"]``）。MUST NOT 用于跨世界
        合并（那是 :meth:`merge_universes`）。返回是否登记成功（元节点不存在则 False）。
        """
        canonical = self._find_universe_canonical(canonical_work_id)
        if canonical is None:
            return False
        for node in self.store.get_all_nodes():
            if (node.extensions or {}).get("universe_meta") and node.name == canonical:
                slot = node.extensions.setdefault("alias_index", {}).setdefault(
                    "aliases", []
                )
                if alias and alias not in slot and alias != node.name:
                    slot.append(alias)
                    # 增量更新注册表倒排（缓存已建时）：alias → canonical
                    if self._universe_index is not None:
                        self._universe_index[alias] = canonical
                self._notify_indexes([node])
                return True
        return False

    def merge_universes(self, src_universe: str, dst_universe: str) -> None:
        """合并两个已存在 canonical universe（**默认关闭**，最危险操作）。

        误并即污染真值（虚构渗入现实），故框架默认永不自动执行。本 change 仅留入口
        骨架——实际合并逻辑（成员 ``universe`` 标量改写、元节点合并、跨 universe 边
        转同 universe 边）需显式高门槛动作启用，不在本 change 实现（宁裂不并）。
        """
        raise NotImplementedError(
            "universe 合并默认关闭（误并污染真值）；需显式高门槛动作，本 change 未实现。"
        )

    def _rule_ingest(
        self, data: IngestInput, universe: str = REALITY_UNIVERSE
    ) -> tuple[Node, list[Node]]:
        """阶段 ⓪：规则入库（不经 LLM）——建记录事件 + source 节点，**不连背书边**。

        事件节点记本次 ingest 的整个 ``content``（落时间轴：``timestamp`` 或 now 兜底），
        ``universe`` 固定 ``__reality__``（摄入行为归属现实）；source 按 ``data.source``
        切分、``universe`` = ``universe``（随本次归属）。背书目标（本次抽出的概念 / 事实）
        的 id 要到 ⑤ 图更新后才确定，故此处只建节点，背书边由 ``_apply_endorsements`` 单独连。
        """
        timestamp = data.timestamp or _now_iso()
        event_name = data.event_name or _derive_event_name(data.content)
        event_node = self._build_event_node(
            EventData(name=event_name, content=data.content, timestamp=timestamp)
        )
        source_nodes: list[Node] = []
        if data.source is not None:
            source_nodes = self._build_source_nodes(data.source, universe)
        return event_node, source_nodes

    def _build_event_node(self, event_data: EventData) -> Node:
        """事件建节点原语（不经 LLM，不连边）。

        创建 ``CLASS_EVENT`` 节点并注入 ``extensions.event_meta``
        （``timestamp`` / ``targets``）。背书边由 ``_connect_endorsement_edges`` 单独连。
        """
        meta: dict[str, Any] = {"targets": list(event_data.target_ids)}
        if event_data.timestamp:
            meta["timestamp"] = event_data.timestamp
        ext = dict(event_data.extensions or {})
        ext["event_meta"] = meta

        node = Node(
            id=str(uuid.uuid4()),
            name=event_data.name,
            content=event_data.content,
            node_class=CLASS_EVENT,
            universe=REALITY_UNIVERSE,  # 摄入行为事件固定现实世界（不随被读作品变）
            extensions=ext,
        )
        self.store.add_node(node)
        return node

    def _build_source_nodes(self, source_data: SourceData, universe: str = REALITY_UNIVERSE) -> list[Node]:
        """Source 建节点原语（不经 LLM，不连边）。

        每个 chunk 对应一个 ``CLASS_SOURCE`` 节点并注入 ``extensions.source_meta``
        （``source_type`` / ``chunk`` / ``targets``）。无 chunks 时整条 source 作为一个节点。
        背书边由 ``_connect_endorsement_edges`` 单独连。
        """
        # 若无 chunks，整条 source 作为一个节点
        chunks = source_data.chunks
        if not chunks:
            chunks = [{"content": source_data.name}]

        created: list[Node] = []
        for chunk in chunks:
            content = chunk.get("content", "")
            chunk_meta = {k: v for k, v in chunk.items() if k != "content"}
            meta = {
                "source_type": source_data.source_type,
                "chunk": chunk_meta,
                "targets": list(source_data.target_ids),
            }
            ext = dict(source_data.extensions or {})
            ext["source_meta"] = meta

            node = Node(
                id=str(uuid.uuid4()),
                name=source_data.name,
                content=content,
                node_class=CLASS_SOURCE,
                universe=universe,  # source 随本次 ingest 归属（work_id 或现实）
                extensions=ext,
            )
            self.store.add_node(node)
            created.append(node)
        return created

    def _build_work_event_nodes(self, ctx: WriteContext) -> list[Node]:
        """阶段 ⑤b：作品叙事事件建节点（消费 ③b 的 ``WorkEventDraft``）。

        - 事件节点：``universe=ctx.target_universe``、``node_class=事件``、
          ``event_meta.timestamp=作品纪年``（``None`` 则不写，时间线排序垫底）；
          落 ``ctx.work_event_nodes``（不进 ``changed``——与现实摄入事件对称，
          事件名不进 alias 索引）。
        - ``participants``（名字）**限同 universe 解析**（复用 ``_apply_decisions``
          的同名去重口径 ``_norm_name``）：命中同 universe 同名核心节点则复用其 id、
          未命中新建概念（``universe=work``）；MUST NOT 跨 universe 连参与者
          （作品事件只背书作品概念，跨 universe 桥另走 ``link_cross_universe``）。
        - 背书边：``事件 —关联→ 参与者概念``（载重规则下核心侧不反查、事件侧可达）。

        返回**新建的参与者概念**列表（并入 ``ctx.changed``：随后被摄入事件 / source
        背书、挂 source_tracking、过阶段 ⑥ 守门）。
        """
        universe = ctx.target_universe
        # 同 universe 同名解析索引（仅核心节点；跨 universe 不解析、不复用）
        by_name: dict[str, str] = {}
        for n in self.store.get_all_nodes():
            if n.node_class not in CORE_NODE_CLASSES or n.universe != universe:
                continue
            key = _norm_name(n.name)
            if key:
                by_name.setdefault(key, n.id)

        new_concepts: list[Node] = []
        for draft in ctx.work_events:
            participant_ids: list[str] = []
            seen: set[str] = set()
            for pname in draft.participants:
                key = _norm_name(pname)
                if not key or key in seen:
                    continue
                seen.add(key)
                pid = by_name.get(key)
                if pid is None or self.store.get_node(pid) is None:
                    pnode = Node(
                        id=str(uuid.uuid4()),
                        name=pname,
                        content=pname,
                        node_class=CLASS_CONCEPT,
                        universe=universe,
                    )
                    self.store.add_node(pnode)
                    new_concepts.append(pnode)
                    by_name[key] = pnode.id
                    pid = pnode.id
                participant_ids.append(pid)

            meta: dict[str, Any] = {
                "targets": list(participant_ids),
                "participants": list(participant_ids),
            }
            if draft.narr_timestamp:
                meta["timestamp"] = draft.narr_timestamp
            event = Node(
                id=str(uuid.uuid4()),
                name=draft.name,
                content=draft.content,
                node_class=CLASS_EVENT,
                universe=universe,  # 作品叙事事件归属作品 universe（≠ 摄入事件的 __reality__）
                extensions={"event_meta": meta},
            )
            self.store.add_node(event)
            ctx.work_event_nodes.append(event)
            self._connect_endorsement_edges(event.id, participant_ids, kind="work_event")
        return new_concepts

    def _connect_endorsement_edges(
        self, endorser_id: str, target_ids: list[str], kind: str = "endorse"
    ) -> None:
        """对一个源端节点（事件 / source）到 ``target_ids`` 各建一条 ``关联`` 背书边。

        目标不存在则跳过并告警（不建悬空边）。``kind`` 仅用于日志。
        载重规则——核心节点 ``get_relations`` 过滤对端为事件的关联边——由 store 层落实，
        此处只建 ``事件/source → 目标`` 的正向边（事件 / source 为源端）。
        """
        for tid in target_ids:
            if self.store.get_node(tid) is not None:
                self.store.add_edge(endorser_id, tid, type=EDGE_ASSOC)
            else:
                logger.warning("%s: 目标节点 %s 不存在，跳过背书边", kind, tid)

    def _apply_endorsements(self, ctx: WriteContext) -> None:
        """阶段 ⑤ 后：把 ⓪ 建的事件 / source 对本次新建 / 命中的概念 / 事实连背书边。

        方向固定：事件 / source（源端）→ 概念 / 事实（目标端）。``event_meta.targets`` /
        ``source_meta.targets`` 回填为本次目标 id（冗余存储，与边一致）。无 changed 核心
        节点时（如全部 no_op）不连边——事件 / source 仍入库，只是无背书对象。
        """
        target_ids = [n.id for n in ctx.changed if n.node_class in CORE_NODE_CLASSES]
        if not target_ids:
            return
        endorsers: list[tuple[Node, str]] = []
        if ctx.event_node is not None:
            endorsers.append((ctx.event_node, "event_meta"))
        endorsers.extend((s, "source_meta") for s in ctx.source_nodes)
        for node, meta_key in endorsers:
            self._connect_endorsement_edges(node.id, target_ids, kind="ingest")
            meta = (node.extensions or {}).get(meta_key)
            if isinstance(meta, dict):
                existing = set(meta.get("targets") or [])
                meta["targets"] = sorted(existing | set(target_ids))

    def _dispatch_merge(self, decision: Decision, universe: str = REALITY_UNIVERSE) -> None:
        """合并：把新概念的名称/别名并入 ``target_id`` 的别名槽，并把
        concept content **语义合并**到目标节点的 content（非子串时 LLM 合并成一个
        稳定定义；落实 unified-graph-schema content 合并守则，不机械追加）。

        直接 mutate ``node.extensions`` / ``node.content``；
        写完后 ``_notify_indexes`` 会重新索引该节点。
        """
        node = self.store.get_node(decision.target_id)  # type: ignore[arg-type]
        if node is None:
            return
        # 同 universe 前置判：跨 universe MUST NOT 合并（演义曹操 ≠ 正史曹操）。
        # query_nodes universe 限域下 target 应同 universe，此为防御。
        if node.universe != universe:
            logger.warning(
                "跨 universe merge 被拒绝：%s(%s) != 本次 %s",
                node.name, node.universe, universe,
            )
            return
        # 1) 别名并入 extensions["alias_index"]["aliases"]（AliasIndexPlugin 读取的槽）
        aliases_to_add = list(decision.aliases_to_add)
        if decision.concept and decision.concept.name:
            aliases_to_add.append(decision.concept.name)
        if aliases_to_add:
            slot = node.extensions.setdefault("alias_index", {"aliases": []})
            existing = slot.setdefault("aliases", [])
            for alias in aliases_to_add:
                # 仅收字符串：非 str（LLM 偶发对象格式）进图会毒化 alias 槽、
                # 崩掉 AliasIndexPlugin.build（unhashable dict）——写入侧最后闸门
                if not isinstance(alias, str):
                    logger.warning("忽略非字符串别名 %r（node=%s）", alias, node.name)
                    continue
                if alias and alias != node.name and alias not in existing:
                    existing.append(alias)
        # 2) concept content 语义合并到目标节点 content（非子串时 LLM 合并成一个
        #    稳定定义；落实 unified-graph-schema content 合并守则，不机械追加）。
        #    node_class 必须穿透到 prompt——概念零时间，事实要保留固定历史时间。
        if decision.concept and decision.concept.content:
            node_class = node.node_class or CLASS_CONCEPT
            node.content = merge_content(
                node.content or "",
                decision.concept.content,
                merge_llm=lambda t, i: self._merge_content_llm(t, i, node_class),
            )
        # 3) content 压缩：合并后超阈值时调用 LLM 压缩，防止单节点 content 无界增长
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

    def _merge_content_llm(
        self, target: str, incoming: str, node_class: str = CLASS_CONCEPT
    ) -> str:
        """``merge_content`` helper 的 LLM 回调：调 ``merge_content`` purpose
        语义合两段 content 成一个稳定定义（按节点类型守时间归属：概念零时间、
        事实禁相对/单次时间但保留固定历史时间）。

        ``node_class`` 必须传入 free_args——模板含 ``{node_class}`` 占位符，
        ``_safe_format`` 遇缺占位符会整体不格式化。
        """
        return self.llm.call(
            purpose="merge_content",
            free_args={
                "target": target,
                "incoming": incoming,
                "node_class": node_class,
            },
        )

    def _dispatch_create(self, decision: Decision, universe: str = REALITY_UNIVERSE) -> Node:
        """创建：新节点 + 到 ``edges_to`` 中每个锚点的关联边。

        统一模型下：
        - 概念间关联为 ``关联`` 边（无 label；开放谓词落事实节点 content）
        - ``node_class`` 从 decision 读取：概念（默认）或事实
        """
        c = decision.concept
        if c is None:
            raise InvalidDecisionError("create without concept payload")
        # node_class 优先级：decision.node_class > concept.node_class > 默认概念
        nc = decision.node_class or getattr(c, "node_class", CLASS_CONCEPT) or CLASS_CONCEPT
        node = Node(
            id=str(uuid.uuid4()),
            name=c.name,
            content=c.content,
            node_class=nc,
            universe=universe,
        )
        self.store.add_node(node)
        for edge_info in decision.edges_to or []:
            anchor_id = edge_info.get("target_id", edge_info) if isinstance(edge_info, dict) else edge_info
            self.store.add_edge(node.id, anchor_id, type=EDGE_ASSOC)
        return node

    def _merge_concept_into(
        self, existing_id: str, decision: Decision, universe: str = REALITY_UNIVERSE
    ) -> Node:
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
            ),
            universe,
        )
        for edge_info in decision.edges_to or []:
            anchor_id = edge_info.get("target_id", edge_info) if isinstance(edge_info, dict) else edge_info
            self.store.add_edge(existing_id, anchor_id, type=EDGE_ASSOC)
        return self.store.get_node(existing_id)

    def _hierarchy_over_budget(self, node: Node) -> bool:
        """节点的层级视图（中心 content + 下钻成员）是否超 T（守门口径，不含关系边）。

        与 fanout_reducer 的 fanout 守门同口径：decide_hub 只看节点、聚不了关系边，
        故关系边 token 不计入（其有界由查询侧 Phase 2 priority 截断兜）。
        """
        if self.token_budget is None:
            return False
        total = self.token_budget.estimate_node(node)
        for child in self.store.get_out_hierarchy(
            node.id, universe=node.universe
        ) or []:
            total += self.token_budget.estimate_node(child)
            if total > self.token_budget.T:
                return True
        return total > self.token_budget.T

    def _run_compaction(self, changed_nodes: list[Node]) -> None:
        """阶段 ⑥：守门核心兜底 + CompactionPlugin 链。

        核心不变量由本方法兜底：changed_nodes 中任一节点层级视图超 T 时，MUST 强制
        运行 CompactionPlugin（忽略 should_run）；若**无任何 CompactionPlugin**而存在
        超 T 节点，logger.error 显式暴露（不变量无法保证，不静默）。无压力时尊重各插件
        should_run（既有行为）。
        """
        from mcs.core.plugin import PluginType

        plugins = self.plugin_manager.get_all(PluginType.COMPACTION)
        # 核心兜底：检测超 T 的层级视图（不依赖插件 should_run）
        pressured = [n for n in changed_nodes if self._hierarchy_over_budget(n)]
        if pressured and not plugins:
            logger.error(
                "写入后存在超 T 节点但无 CompactionPlugin——核心不变量无法保证: %s",
                [n.id for n in pressured],
            )
        for plugin in plugins:
            if pressured or plugin.should_run(changed_nodes, self.store):
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
    ``{concepts}`` 占位符。事实节点前置 ``[事实]`` 标记。
    """
    lines = []
    for i, c in enumerate(concepts, 1):
        prefix = "[事实] " if c.node_class == "事实" else ""
        lines.append(f"{i}. {prefix}{c.name}: {c.content}")
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


def _now_iso() -> str:
    """当前**本地**时间的 ISO 8601 裸字符串（秒级），用作事件节点 ``timestamp`` 缺省值。

    与碎片确认入图的时间戳（``YYYY-MM-DDTHH:MM:SS``，本地裸时间）同形态——统一形态
    使字典序即时间序；历史 UTC aware 存量由 ``mcs.utils.timestamps`` 的排序键兼容。
    """
    return datetime.now().isoformat(timespec="seconds")


def _derive_event_name(content: str) -> str:
    """从 content 规则派生事件节点 name（缺省口径）：去空白换行、截断至 40 字、空则 "ingest"。

    允许 ``IngestInput.event_name`` 覆盖；缺省截断派生仅为可观测 / 反查友好，无语义含义。
    """
    text = " ".join((content or "").split())
    if not text:
        return "ingest"
    return text[:40] + ("…" if len(text) > 40 else "")
