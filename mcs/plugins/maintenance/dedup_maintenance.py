"""去重维护插件 — 后台扫描同名/同义节点并合并。

触发路径（§5.1 收敛表）：
  ① 创建时对齐（write_pipeline）  ✅
  ② 读取碰到（read-repair）       ✅
  ③ 聚类时合并同义（fanout_reducer）✅
  ④ 后台维护扫描（本插件）         可选，兜底长尾残留

本插件扫描全图节点，按 name 分组找同名节点对，执行合并（别名+content 追加）。
Phase 1 仅做同名字面识别；同义判定留 Phase 2（embedding/LLM）。

按 unified-graph-schema「图质量最终收敛」requirement，后台去重允许合并同名
核心节点（含事实，背书/互斥边重挂）；**互为互斥**的同名节点不合并（避免自互斥/
矛盾塌缩）。注意：聚类裂变（fanout_reducer）对事实仍只重组不合并——本插件属
后台去重，与聚类是不同操作。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from mcs.entities.graph import CORE_NODE_CLASSES, EDGE_ASSOC, EDGE_MUTEX, Node
from mcs.interfaces.maintenance import MaintenanceInterface

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginContext
    from mcs.core.store import StoreInterface
    from mcs.core.token_budget import TokenBudget

logger = logging.getLogger(__name__)


def _merge_aliases(node_id: str, store: StoreInterface, alias_name: str) -> None:
    """向节点的 alias_index.aliases 追加一个别名（幂等，不重复写入）。"""
    node = store.get_node(node_id)
    if node is None:
        return
    aliases = node.extensions.setdefault("alias_index", {}).setdefault("aliases", [])
    if alias_name and alias_name not in aliases and alias_name != node.name:
        aliases.append(alias_name)
    store.update_node(node_id, {"extensions": node.extensions})


class DedupMaintenance(MaintenanceInterface):
    """去重维护插件：扫描同名节点并合并。

    - 同名字面识别（零成本）
    - 合并策略：别名并入 + content 追加（子串去重）
    - 合并核心节点（概念 / 事实）；事件 / source 不走合并
    - 合并后估算 target token，超 T 则跳过（挂起，待写 / 维护路径触发聚类）
    - 重挂边时补查事件背书边（绕载重规则），避免背书丢失
    - **互为互斥的同名节点不合并**（避免自互斥 / 矛盾塌缩）
    - should_run() 默认返回 False，由外部调度器控制触发
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        # token_budget 经 initialize(context) 注入（与 FanoutReducerPlugin 一致）；
        # builder 用 cls(plugin_config) 实例化、initialize_all 注入。单测未注入时
        # 为 None，run() 走"无守门"分支不崩。
        self.token_budget: TokenBudget | None = None

    def initialize(self, context: PluginContext) -> None:
        """从 PluginContext 注入 token_budget（builder 实例化后由 initialize_all 调用）。"""
        self.token_budget = context.token_budget

    def get_name(self) -> str:
        return "dedup_maintenance"

    def should_run(self) -> bool:
        """默认不自动运行——由外部调度器控制触发时机与算力预算。"""
        return False

    @staticmethod
    def _has_mutex_between(store: StoreInterface, a_id: str, b_id: str) -> bool:
        """两节点之间是否存在互斥边（任一方向）。"""
        for e in store.get_edges_between(a_id, b_id):
            if e.type == EDGE_MUTEX:
                return True
        for e in store.get_edges_between(b_id, a_id):
            if e.type == EDGE_MUTEX:
                return True
        return False

    def run(self, store: StoreInterface) -> None:
        """扫描全图，合并同名核心节点。"""
        nodes = store.get_all_nodes()
        # 按 name 分组（仅核心节点）
        by_name: dict[str, list[str]] = defaultdict(list)
        for node in nodes:
            if node.node_class in CORE_NODE_CLASSES and node.name:
                by_name[node.name].append(node.id)

        merged_count = 0
        hung_count = 0
        for name, ids in by_name.items():
            if len(ids) < 2:
                continue
            # 保留第一个，合并其余
            target_id = ids[0]
            for dup_id in ids[1:]:
                target = store.get_node(target_id)
                dup = store.get_node(dup_id)
                if target is None or dup is None:
                    continue

                # 安全闸：dup 与 target 互为互斥（同名但矛盾）→ 不合并，
                # 避免合并后产生自互斥 / 矛盾塌缩（合并事实的已知边界）。
                if self._has_mutex_between(store, target_id, dup_id):
                    logger.info(
                        "去重维护：%s(%s) 与 %s(%s) 互为互斥，跳过合并",
                        target.name, target_id, dup.name, dup_id,
                    )
                    continue

                # 模拟合并后的 content（子串去重）
                merged_content = target.content or ""
                if dup.content and dup.content not in (target.content or ""):
                    merged_content = (target.content or "") + "\n" + dup.content

                # 守门：估算合并后 target token，超 T 则挂起（跳过）
                if self.token_budget is not None:
                    # 用临时节点估算合并后的 token
                    temp = Node(
                        id=target.id, name=target.name, content=merged_content,
                        node_class=target.node_class, extensions=target.extensions,
                    )
                    est = self.token_budget.estimate_node(temp)
                    if est > self.token_budget.T:
                        hung_count += 1
                        logger.info(
                            "去重维护：合并 %s(%s) → %s(%s) 超 T（%d > %d），挂起",
                            dup.name, dup_id, target.name, target_id,
                            est, self.token_budget.T,
                        )
                        continue

                # content 追加（子串去重）
                target.content = merged_content

                # 别名追加（用 helper）
                _merge_aliases(target_id, store, dup.name)

                # 更新目标节点 content
                store.update_node(target_id, {
                    "content": target.content,
                })

                # 重挂 dup 的关联/互斥边到 target
                for edge in store.get_relations(dup_id):
                    if edge.source_id == dup_id:
                        store.add_edge(target_id, edge.target_id, type=edge.type)
                    elif edge.target_id == dup_id:
                        store.add_edge(edge.source_id, target_id, type=edge.type)

                # 补挂事件背书边：get_related_events 绕过载重规则拿到 事件→dup
                for ev in store.get_related_events(dup_id):
                    store.add_edge(ev.id, target_id, type=EDGE_ASSOC)

                # 删除重复节点
                store.delete_node(dup_id)
                merged_count += 1

                logger.info(
                    "去重维护：合并 %s(%s) → %s(%s)",
                    dup.name, dup_id, target.name, target_id,
                )

        if merged_count or hung_count:
            logger.info(
                "去重维护完成：合并 %d 对同名节点，挂起 %d 对（超 T）",
                merged_count, hung_count,
            )
