## 1. MCS 类移入 core

- [ ] 1.1 创建 `mcs/core/mcs.py`，从 `mcs/__init__.py` 移入 MCS 类定义
- [ ] 1.2 移除 MCS 类中的 `_default_plugin_registry` 内联引用，改为 `plugin_registry` 参数注入
- [ ] 1.3 保留 MCS 类的 `initialize()` 逻辑，适配 `plugin_registry` 参数
- [ ] 1.4 更新 `mcs/core/__init__.py`，导出 `MCS` 和 `MCSBuilder`

## 2. MCSBuilder 抽象类

- [ ] 2.1 创建 `mcs/core/builder.py`，定义 `MCSBuilder` ABC
- [ ] 2.2 实现抽象方法 `get_plugin_class(name: str) -> type[Plugin] | None`
- [ ] 2.3 实现具体方法 `build() -> MCS`，封装从配置到初始化的完整流程
- [ ] 2.4 实现 `_collect_registry()` 辅助方法，从 `config.plugins` 收集插件类

## 3. presets 脚手架模块

- [ ] 3.1 创建 `mcs/presets/__init__.py`，导出 `create_mcs` 和 `Phase1Builder`
- [ ] 3.2 创建 `mcs/presets/phase1.py`，实现 `get_phase1_plugin_registry()` 函数
- [ ] 3.3 实现 `Phase1Builder` 类，继承 `MCSBuilder`
- [ ] 3.4 实现 `create_mcs()` 快捷工厂函数

## 4. mcs/__init__.py 重构

- [ ] 4.1 将 `mcs/__init__.py` 改为从 `core` 和 `presets` 导入导出
- [ ] 4.2 设置 `_default_plugin_registry = get_phase1_plugin_registry` 兼容别名
- [ ] 4.3 更新 `__all__` 列表，新增 `MCSBuilder`、`create_mcs`

## 5. Bench 代码适配

- [ ] 5.1 更新 `mcs/bench/multihop_rag.py` 的 `_make_mcs()` 改用 `create_mcs()` 或 `Phase1Builder`
- [ ] 5.2 验证 `mcs/bench/hotpot.py` 的 MCS 创建方式兼容

## 6. 测试与验证

- [ ] 6.1 验证 `from mcs import MCS, MCSConfig` 仍正常工作
- [ ] 6.2 验证 `from mcs import _default_plugin_registry` 兼容别名正常
- [ ] 6.3 验证 `MCSBuilder` 可被子类化并自定义插件查找
- [ ] 6.4 验证 `create_mcs()` 快捷工厂可创建完整 MCS 实例
- [ ] 6.5 运行全量测试确保无回归
- [ ] 6.6 验证 `mcs/core/` 不导入 `mcs/plugins/` 或 `mcs/presets/`

## 7. 文档更新

- [ ] 7.1 更新 `mcs/core/__init__.py` docstring 说明新增模块
- [ ] 7.2 更新 CLAUDE.md 中 MCS 类相关说明（如有）
