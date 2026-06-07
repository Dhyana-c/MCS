## Context

### 当前问题
`PostprocessPluginInterface` 同时用于查询前置（阶段 ①）、查询后置（阶段 ⑤）、写入前置（阶段 ①），仅靠 `position` 字符串属性区分：
- `query_preprocess`：查询前置
- `query_postprocess`：查询后置
- `write_preprocess`：写入前置

类型系统无法静态约束，运行时靠字符串匹配，易出错且难维护。

### 受影响插件
- `IdempotencyCheckPlugin`（`source_tracking.py`）：`position="write_preprocess"`
- `RerankPlugin`（`rerank.py`）：`position="query_postprocess"`

### 约束
- 保持与现有 `PostprocessPluginInterface` 链式调用语义
- 不修改 `process(input, ctx)` 方法签名
- 迁移路径清晰，避免破坏现有功能

## Goals / Non-Goals

**Goals:**
- 引入独立的 `PluginType.PREPROCESS` 和 `PreprocessPluginInterface`
- 查询和写入管线的前置处理使用独立类型
- 删除 `PostprocessPluginInterface.position` 属性
- 迁移现有使用 `position` 的插件

**Non-Goals:**
- 不修改 `PostprocessPluginInterface.process` 方法签名
- 不修改后置插件的链式调用逻辑
- 不涉及 `_traverse` 或种子选择逻辑（属于 `token-budget-traverse` 变更）

## Decisions

### D1: PREPROCESS 类型用于查询和写入的前置处理

**决定**：`PluginType.PREPROCESS` 同时服务于查询管线和写入管线的前置处理。

**理由**：
- 前置处理的职责相同：文本预处理（幂等检查、摘要、清洗等）
- 输入输出类型相同：`str → str`
- 避免过度拆分（`QUERY_PREPROCESS` + `WRITE_PREPROCESS` 会增加复杂性）

**替代方案**：
- 分离为 `QUERY_PREPROCESS` 和 `WRITE_PREPROCESS` → 职责相同，过度设计
- 保留 `position` 属性但增加类型校验 → 治标不治本

### D2: PreprocessPluginInterface 方法签名为 `preprocess(text: str, ctx) -> str`

**决定**：新接口定义 `preprocess(text, ctx)` 而非复用 `process(input, ctx)`。

**理由**：
- 类型明确：输入输出都是 `str`，而非 `Any`
- 语义清晰：方法名表达意图
- 与 `PostprocessPluginInterface.process(input: Any, ctx)` 区分

**接口设计**：
```python
class PreprocessPluginInterface(Plugin):
    def get_type(self) -> PluginType:
        return PluginType.PREPROCESS

    @abstractmethod
    def preprocess(self, text: str, ctx) -> str:
        """预处理文本，返回处理后的文本。"""
        pass

    def execute(self, **kwargs) -> str:
        return self.preprocess(
            text=kwargs["text"],
            ctx=kwargs.get("ctx"),
        )
```

### D3: PostprocessPluginInterface 删除 position 属性

**决定**：删除 `position` 属性，`PostprocessPluginInterface` 专用于后置处理。

**理由**：
- 类型安全：不再依赖字符串匹配
- 简化接口：单一职责

**迁移路径**：
- `IdempotencyCheckPlugin`：从 `PostprocessPluginInterface` 迁移到 `PreprocessPluginInterface`
  - `process(input, ctx)` → `preprocess(text, ctx)`
  - 删除 `position` 属性
- `RerankPlugin`：保持 `PostprocessPluginInterface`，删除 `position` 属性

### D4: 删除 _read_chain_for_position 方法

**决定**：删除 `QueryEngine._read_chain_for_position` 和 `WritePipeline` 中的类似逻辑。

**理由**：
- 不再需要按 `position` 筛选
- 直接使用 `plugin_manager.get_all(PluginType.PREPROCESS)` 或 `POSTPROCESS`

## Risks / Trade-offs

### R1: IdempotencyCheckPlugin 迁移风险
**风险**：`IdempotencyCheckPlugin` 从 `PostprocessPluginInterface` 迁移到 `PreprocessPluginInterface`，方法签名从 `process(input: Any, ctx)` 改为 `preprocess(text: str, ctx)`。

**缓解**：
- 该插件当前实现中 `process` 已假设输入是 `str`（幂等检查基于文本内容）
- 迁移只需改方法名和类型声明，逻辑不变
- 提供迁移文档

### R2: 第三方插件兼容性
**风险**：如果有外部插件使用 `position` 属性，会因属性删除而失效。

**缓解**：
- Phase 1 默认插件已覆盖，外部插件影响可控
- 在 release note 中明确标注 breaking change

## Migration Plan

### 阶段 1: 新增类型和接口（无破坏性）
1. 在 `PluginType` 中新增 `PREPROCESS`
2. 创建 `PreprocessPluginInterface`
3. 更新 `PluginManager` 支持新类型

### 阶段 2: 修改管线
1. 修改 `QueryEngine._run_preprocess` 使用 `PluginType.PREPROCESS`
2. 修改 `WritePipeline._run_preprocess` 使用 `PluginType.PREPROCESS`
3. 删除 `_read_chain_for_position` 方法

### 阶段 3: 迁移插件
1. `IdempotencyCheckPlugin` 迁移为 `PreprocessPluginInterface`
2. `RerankPlugin` 删除 `position` 属性

### 阶段 4: 清理
1. 删除 `PostprocessPluginInterface.position` 属性
2. 更新文档

### 回滚策略
- 若迁移困难，可临时保留 `position` 属性（标记 deprecated）
- 管线可同时支持新类型和旧 `position` 筛选（兼容层）
