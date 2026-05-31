## 1. 配置层改动

- [x] 1.1 MCSConfig 新增 `auto_persist: bool = True` 字段
- [x] 1.2 更新 MCSConfig.knowledge_graph() 默认配置包含 auto_persist

## 2. WriteContext 扩展

- [x] 2.1 WriteContext 新增 `persisted: bool = False` 字段

## 3. WritePipeline 阶段 ⑦ 实现

- [x] 3.1 新增 `_run_persist(ctx)` 方法实现增量落盘逻辑
- [x] 3.2 从 PluginManager 获取 StorageInterface
- [x] 3.3 遍历 ctx.changed 调用 save_node()
- [x] 3.4 推导并持久化新增边（遍历 changed 节点的邻接边）
- [x] 3.5 捕获存储异常并记录警告，不抛出到调用方
- [x] 3.6 检查 config.auto_persist 开关决定是否执行
- [x] 3.7 在 ingest() 中阶段 ⑥ 之后调用 _run_persist()

## 4. MCS initialize() load-on-startup

- [x] 4.1 在 initialize() 末尾检查 StorageInterface 是否注册
- [x] 4.2 检查 graph.get_all_nodes() 是否为空
- [x] 4.3 若为空且 Storage 存在，调用 storage.load() 填充 graph
- [x] 4.4 捕获 load 异常并记录警告，不影响初始化完成

## 5. 测试覆盖

- [x] 5.1 测试 auto_persist=True 时每次 ingest 后节点落盘
- [x] 5.2 测试 auto_persist=False 时跳过落盘
- [x] 5.3 测试 load-on-startup 从已有数据库恢复图
- [x] 5.4 测试 WriteContext.persisted 字段正确设置
- [x] 5.5 测试存储异常时不影响 ingest 返回

## 6. 文档更新

- [x] 6.1 更新 README.md 说明自动落盘机制
- [x] 6.2 更新 architecture.md 记录 7 段写入管线
