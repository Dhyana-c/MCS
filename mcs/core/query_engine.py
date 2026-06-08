"""查询引擎 - 从 MCS 读取的 5 阶段管道。

5 个阶段按顺序执行，参见 openspec/specs/query-pipeline/spec.md：

    ① 前置插件链      (PostprocessPlugin chain, 可选)
    ② 种子定位        (EntryPlugin chain + TrimPlugin)
    ③ 语义理解 Loop   (BFS + visited + max_rounds + token_budget)
    ④ 仲裁            (ArbitrationPlugin, ≤1)
    ⑤ 后置处理链      (PostprocessPlugin chain)

默认返回值为 ``List[Node]``（``QueryContext`` 的 ``result_set`` 字段）。
合成为自然语言字符串是可选的，由阶段 ⑤ 中的后处理插件提供。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcs.core.graph import Node
    from mcs.core.plugin_manager import PluginManager
    from mcs.core.store import StoreInterface
    from mcs.core.token_budget import TokenBudget
    from mcs.interfaces.llm import LLMInterface

logger = logging.getLogger(__name__)


@dataclass
class QueryContext:
    """贯穿一次 query() 调用的状态。

    规范中的 4 个生命周期字段：

    - ``system_prompt``: 用户配置的（领域 + 角色），不变量
    - ``user_input``: 原始查询字符串，不变量
    - ``intermediate``: 在阶段 ③ Loop 中 ``accumulated``
    - ``result_set``: 阶段 ④ 后的最终选定节点集

    参见 openspec/specs/query-pipeline/spec.md "QueryContext 含四个状态字段"。
    """

    system_prompt: str = ""
    user_input: str = ""
    intermediate: list[Node] = field(default_factory=list)
    result_set: list[Node] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class QueryEngine:
    """读取管道协调器。

    组合：graph + llm + 插件链 + token 预算。插件链在调用时从 ``plugin_manager``
    读取，因此支持在调用之间动态（取消）注册插件。
    """

    def __init__(
            self,
            store: StoreInterface,
            llm: LLMInterface,
            plugin_manager: PluginManager,
            token_budget: TokenBudget,
            max_rounds: int = 5,
            max_accumulated_nodes: int = 1000,
            system_prompt: str = "",
    ):
        self.store = store
        self.llm = llm
        self.plugin_manager = plugin_manager
        self.token_budget = token_budget
        self.max_rounds = max_rounds
        self.max_accumulated_nodes = max_accumulated_nodes
        self.system_prompt = system_prompt

    # === 公共 API ===

    def query(
            self,
            text: str,
            existing_context: list[Node] | None = None,
    ) -> Any:
        """执行 5 阶段读取管道。

        返回最后一个后处理插件的输出，如果没有后处理插件转换类型，
        则返回 ``result_set`` (List[Node])。
        """
        ctx = QueryContext(
            system_prompt=self.system_prompt,
            user_input=text,
        )

        # 阶段 ①: 前置插件链（可选；应用于查询文本）
        processed_text = self._run_preprocess(text, ctx)

        # 阶段 ②: 种子定位（如果提供了 existing_context 则跳过）
        if existing_context is not None:
            seeds = list(existing_context)
        else:
            seeds = self._locate_seeds(processed_text, ctx)

        # 阶段 ③: 语义理解 Loop
        ctx.intermediate = self._traverse(seeds, processed_text, ctx)

        # 阶段 ④: 仲裁
        ctx.result_set = self._arbitrate(ctx.intermediate, processed_text, ctx)

        # 阶段 ⑤: 后置处理链
        return self._run_postprocess(ctx.result_set, ctx)

    # === 阶段辅助方法 ===

    def _run_preprocess(self, text: str, ctx: QueryContext) -> str:
        """阶段 ①：将文本作为输入的串行 QueryPreprocessPlugin 链。

        注意：读取管道预处理插件接收字符串并返回（可能转换的）字符串。
        不修改文本的插件应返回未更改的文本。
        """
        from mcs.core.plugin import PluginType

        plugins = self.plugin_manager.get_all(PluginType.QUERY_PREPROCESS)
        if not plugins:
            return text
        result: Any = text
        for plugin in plugins:
            result = plugin.preprocess(result, ctx)
        return result if isinstance(result, str) else text

    def _locate_seeds(self, query: str, ctx: QueryContext) -> list[Node]:
        """阶段 ②：运行所有 EntryPlugins（按优先级排序），合并，裁剪，语义筛选。

        执行顺序：EntryPlugin 链（合并）→ TrimPlugin（硬截断）→ SeedSelectorPlugin 链（语义筛选）
        """
        from mcs.core.plugin import PluginType

        entry_plugins = self.plugin_manager.get_all(PluginType.ENTRY)
        accumulated: list[Node] = []
        seen: set[str] = set()
        exclusive_hit = False

        for plugin in entry_plugins:
            if exclusive_hit and not plugin.exclusive:
                # 更高优先级的独占插件已获胜；跳过低优先级插件
                continue
            candidates = plugin.locate(query, ctx) or []
            if not candidates:
                continue
            for node in candidates:
                if node.id not in seen:
                    seen.add(node.id)
                    accumulated.append(node)
            if plugin.exclusive:
                exclusive_hit = True

        # 如果超出预算则裁剪
        trim = self.plugin_manager.get(PluginType.TRIM)
        if trim is not None and accumulated:
            try:
                accumulated = trim.trim(accumulated, self.token_budget.T)
            except NotImplementedError:
                # 预算检查尚未实现；原样传递
                pass

        # SeedSelectorPlugin 链：语义筛选
        selector_plugins = self.plugin_manager.get_all(PluginType.SEED_SELECTOR)
        if selector_plugins and accumulated:
            for selector in selector_plugins:
                try:
                    accumulated = selector.select(
                        seeds=accumulated,
                        query=query,
                        budget=self.token_budget.T,
                        ctx=ctx,
                    )
                except Exception:
                    logger.warning(
                        "SeedSelectorPlugin %s 执行失败，跳过",
                        selector.get_name(),
                        exc_info=True,
                    )

        return accumulated

    def _traverse(
            self,
            seeds: list[Node],
            query: str,
            ctx: QueryContext,
    ) -> list[Node]:
        """阶段 ③：批量邻居扩展的 token 预算驱动 BFS 遍历。

        核心优化：多个节点及其邻居合并后一次 LLM 调用，只要总 token ≤ T*0.8。
        核心不变量保证「任一节点 + 其全部一跳邻居 ≤ 窗口 T」，因此多节点合并后
        单次 select_nodes 调用天然 ≤ T*0.8（80% 余量防估算误差）。

        LLM 选中的邻居里，**已访问的去重丢弃**，未访问的加入 accumulated 并入队。
        ``max_rounds`` 限制 BFS 深度；token 预算 / ``max_accumulated_nodes`` 兜底终止。
        """
        if not seeds:
            return []

        from mcs.core.context_renderer import ContextRenderer
        from mcs.core.errors import LLMParseError
        from mcs.prompts.select_nodes import BATCH_USER_TEMPLATE

        visited: set[str] = set()
        accumulated: list[Node] = []
        queue: list[tuple[Node, int]] = []  # (节点, 自种子起算的深度)
        for seed in seeds:
            if seed.id not in visited:
                visited.add(seed.id)
                accumulated.append(seed)
                queue.append((seed, 0))

        budget = self.token_budget.T
        pack_threshold = budget * 0.8  # 打包阈值，留 20% 余量

        while queue:
            # 安全阀：节点数硬上限
            if len(accumulated) >= self.max_accumulated_nodes:
                logger.info(
                    "遍历达到 max_accumulated_nodes=%d, 终止",
                    self.max_accumulated_nodes,
                )
                break
            # token 预算：accumulated 子图渲染量超窗口则停
            used_tokens = sum(
                self.token_budget.estimate_node(n) for n in accumulated
            )
            if used_tokens >= budget:
                logger.info(
                    "accumulated token=%d >= budget=%d, 终止", used_tokens, budget
                )
                break

            # === 批量打包 ===
            batch_centers: list[tuple[Node, int]] = []  # (中心节点, 深度)
            batch_neighbors: list[Node] = []
            neighbor_to_center: dict[str, tuple[str, int]] = {}  # neighbor_id -> (center_id, center_depth)
            batch_tokens = 0

            # 贪心打包：从 queue 取节点直到接近 pack_threshold
            while queue and batch_tokens < pack_threshold:
                node, depth = queue.pop(0)
                if depth >= self.max_rounds:
                    continue  # 达深度上限：不加入本批次，跳过扩展

                neighbors = self.store.get_neighbors(node.id) or []
                if not neighbors:
                    continue  # 无邻居：不加入本批次

                # 估算本节点的 token（中心 + 邻居）
                node_tokens = self.token_budget.estimate_node(node)
                neighbor_tokens = sum(
                    self.token_budget.estimate_node(n) for n in neighbors
                )
                total_tokens = node_tokens + neighbor_tokens

                # 检查是否超预算
                if batch_tokens + total_tokens > budget:
                    # 单节点超预算 → 仍可加入（不变量保证 ≤ T）
                    if batch_tokens == 0:  # 空批次，加入这单个节点
                        batch_centers.append((node, depth))
                        for neighbor in neighbors:
                            if neighbor.id not in neighbor_to_center:
                                batch_neighbors.append(neighbor)
                                neighbor_to_center[neighbor.id] = (node.id, depth)
                        batch_tokens = total_tokens
                    else:
                        # 预算不足且已有节点，把当前节点放回队列头部
                        queue.insert(0, (node, depth))
                    break  # 预算不足，停止打包

                # 加入批次
                batch_centers.append((node, depth))
                for neighbor in neighbors:
                    if neighbor.id not in neighbor_to_center:
                        batch_neighbors.append(neighbor)
                        neighbor_to_center[neighbor.id] = (node.id, depth)
                batch_tokens += total_tokens

            if not batch_centers:
                continue  # 本轮无可扩展节点

            # === 渲染中心和邻居 ===
            renderer = ContextRenderer(self.plugin_manager)
            centers_text = renderer.render(
                [n for n, _ in batch_centers], purpose="select_nodes"
            )
            neighbors_text = renderer.render(batch_neighbors, purpose="select_nodes")

            # === 批量 LLM 调用 ===
            selected_ids: list[str] = []
            # 构造 nodes_in：所有中心节点 + 所有邻居（保持兼容 LLMInterface.call 标准）
            all_nodes_in = [n for n, _ in batch_centers] + batch_neighbors
            # 保存原模板以便恢复
            original_prompt = self.llm.get_prompt("select_nodes")
            try:
                # 临时注册批量模板
                self.llm.register_prompt("select_nodes", template=BATCH_USER_TEMPLATE)
                selected_ids = self.llm.call(
                    purpose="select_nodes",
                    nodes_in=all_nodes_in,
                    free_args={
                        "query": query,
                        "centers": centers_text,
                        "neighbors": neighbors_text,
                        "accumulated_summary": _summarize_for_prompt(accumulated),
                    },
                ) or []
            except LLMParseError:
                # 回退到逐节点处理
                logger.warning("批量 LLM 调用失败，回退到逐节点处理")
                selected_ids = self._fallback_single_node_select(
                    batch_centers, query, accumulated
                )
            finally:
                # 恢复原模板
                self.llm.register_prompt(
                    "select_nodes",
                    template=original_prompt.template,
                    system=original_prompt.system,
                )

            selected = set(selected_ids)

            # === 归类选中节点 ===
            for neighbor_id in selected:
                if neighbor_id not in visited and neighbor_id in neighbor_to_center:
                    center_id, center_depth = neighbor_to_center[neighbor_id]
                    # 找到 neighbor 节点对象
                    neighbor_node = next(
                        (n for n in batch_neighbors if n.id == neighbor_id), None
                    )
                    if neighbor_node:
                        visited.add(neighbor_id)
                        accumulated.append(neighbor_node)
                        queue.append((neighbor_node, center_depth + 1))
                        if len(accumulated) >= self.max_accumulated_nodes:
                            break

        return accumulated

    def _fallback_single_node_select(
            self,
            batch_centers: list[tuple[Node, int]],
            query: str,
            accumulated: list[Node],
    ) -> list[str]:
        """批量调用失败时，回退到逐节点 LLM 筛选。"""
        selected_ids: list[str] = []
        for center, depth in batch_centers:
            neighbors = self.store.get_neighbors(center.id) or []
            if not neighbors:
                continue
            single_selected = self.llm.call(
                purpose="select_nodes",
                nodes_in=[center, *neighbors],
                free_args={
                    "query": query,
                    "accumulated_summary": _summarize_for_prompt(accumulated),
                },
            ) or []
            selected_ids.extend(single_selected)
        return selected_ids

    def _arbitrate(
            self,
            accumulated: list[Node],
            query: str,
            ctx: QueryContext,
    ) -> list[Node]:
        """阶段 ④：≤1 个 ArbitrationPlugin；默认为直通。"""
        from mcs.core.plugin import PluginType

        plugin = self.plugin_manager.get(PluginType.ARBITRATION)
        if plugin is None:
            return list(accumulated)
        result = plugin.arbitrate(accumulated, query, ctx)
        if not isinstance(result, list):
            raise TypeError(
                f"Arbitration plugin {plugin.get_name()!r} returned non-list "
                f"({type(result).__name__}); arbitration must return List[Node]"
            )
        return result

    def _run_postprocess(self, selected: list[Node], ctx: QueryContext) -> Any:
        """阶段 ⑤：针对查询位置的串行 PostprocessPlugin 链。"""
        from mcs.core.plugin import PluginType

        plugins = self.plugin_manager.get_all(PluginType.POSTPROCESS)
        if not plugins:
            return selected
        result: Any = selected
        for plugin in plugins:
            result = plugin.process(result, ctx)
        return result


def _summarize_for_prompt(nodes: list[Node]) -> str:
    """用于 ``decide_directions`` 调用中累积上下文的紧凑单行每节点摘要。
    避免在重复提示中拖拽完整内容。
    """
    from mcs.core.context_renderer import ContextRenderer

    lines = []
    for node in nodes:
        summary = ContextRenderer.get_summary(node)
        lines.append(f"- {node.name} (id={node.id}): {summary}")
    return "\n".join(lines) if lines else "(无)"
