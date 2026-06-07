"""MCS Presets — 预配置构建器和快捷工厂。

提供 Phase1 默认插件注册表、Phase1Builder 构建器和 create_mcs() 快捷工厂函数，
便于用户快速创建 MCS 实例而无需手动配置插件列表。

参见 openspec/specs/mcs-presets/spec.md。
"""

from __future__ import annotations

from mcs.presets.phase1 import (
    Phase1Builder,
    create_mcs,
    get_phase1_plugin_registry,
)

__all__ = [
    "Phase1Builder",
    "create_mcs",
    "get_phase1_plugin_registry",
]