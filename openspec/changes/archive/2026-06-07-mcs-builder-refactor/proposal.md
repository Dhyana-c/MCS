## Why

当前 MCS 类同时承担了「配置持有者」「插件注册中心」「管线组装器」三重职责，且直接依赖 MCSConfig。用户必须先构造 Config、再手动调用 `initialize()`，流程割裂；`register_plugin()` 注册到两侧 manager 无法区分目标管线；`persist_full()` / `_try_load_from_storage()` 等存储操作不应出现在顶层编排器中。MCS 应退化为只暴露两条管线（writer / reader）的瘦门面，所有初始化和组装工作由 Builder 一次完成。

## What Changes

- **BREAKING** MCS 类不再接受 MCSConfig，不再有 `initialize()` 方法；构造由 Builder 完成，返回即用
- **BREAKING** `register_plugin()` 需指定目标管线（`"writer"` | `"reader"`），不再隐式双注册；新增 `register_shared_plugin()` 便捷方法用于共享注册
- **BREAKING** 移除 `persist_full()` / `_try_load_from_storage()` — 持久化/加载由 Store 直接操作，load-on-startup 由 Builder 执行
- **BREAKING** 移除 MCS 对 `MCSConfig` 的直接依赖；Config 仅作为 Builder 的输入
- Builder 接管全部初始化工作（插件注册、Store 初始化、ContextRenderer 构建、PluginContext 注入、管线构建、load-on-startup）
- 新增 `show()` 方法：以 Markdown 流程图展示 writer / reader 各自的注册插件与处理流程
- 保留 `shutdown()` 方法：去重关闭共享插件实例，优雅释放资源
- MCS 公共 API 简化为 `ingest()` / `query()` / `show()` / `register_plugin(target)` / `register_shared_plugin()` / `unregister_plugin(target)` / `shutdown()`

## Capabilities

### New Capabilities
- `mcs-thin-facade`: MCS 退化为瘦门面——只暴露 writer/reader 双管线、定向插件注册/注销、show() 流程图展示；不再持有 Config 或执行初始化逻辑
- `builder-full-assembly`: Builder 接管全量组装——从 Config + 插件注册表到 Store 初始化、PluginContext 注入、管线构建、load-on-startup，一次 build() 返回即用的 MCS 实例

### Modified Capabilities
- `mcs-builder`: MCSBuilder 抽象基类的 build() 契约变更——不再委托 MCS.initialize()，改为直接组装并返回完成态 MCS
- `plugin-protocol`: 插件注册/注销 API 变更——需指定目标管线（writer/reader），不再支持双注册

## Impact

- **核心代码**：`mcs/core/mcs.py` 大幅瘦身（移除 initialize/config/register_plugin 逻辑），`mcs/core/builder.py` 扩展（接管全部初始化）
- **PluginManager**：新增 `unregister()` 方法
- **预设层**：`mcs/presets/phase1.py` 的 Phase1Builder 适配新 Builder 契约
- **公共 API**：`mcs/__init__.py` 导出调整；`create_mcs()` 工厂函数接口不变但内部走新 Builder
- **测试**：所有 `MCS(config).initialize()` 改为 `Builder(config).build()`；`register_plugin(mock_llm)` 改为 `register_shared_plugin(mock_llm)`
- **示例**：`examples/basic_usage.py` 和 `examples/wiki_example.py` 的 mock 构建方式需更新
- **评测**：`mcs/bench/multihop_rag.py` 中 `persist_full()` 改为 `mcs.store.save_full()`
- **规范**：`openspec/specs/auto-persistence/spec.md` 中 `MCS.initialize()` 引用需更新为 Builder 执行
- **MCSConfig**：不再被 MCS 直接消费，仅作为 Builder 输入；可逐步考虑将配置内联到 Builder 参数
