# Design: preprocess-split — 前置处理插件拆分

## 架构图

```
┌──────────────────────────────────────────────────────────────────────┐
│                    拆分前（当前）                                     │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  PluginType.PREPROCESS                                               │
│       │                                                              │
│       ▼                                                              │
│  PreprocessPluginInterface                                           │
│       │                                                              │
│       │  preprocess(text: str, ctx: Any) -> str                      │
│       │                                                              │
│       ├──────────────────┬───────────────────────────────────────────┤
│       │                  │                                           │
│       ▼                  ▼                                           │
│  WritePipeline      QueryEngine                                      │
│  Stage ①            Stage ①                                          │
│  (WriteContext)     (QueryContext)                                   │
│                                                                      │
│  问题：ctx 类型模糊、短路语义不对称、组合不可控                        │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                    拆分后（目标）                                     │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  PluginType.WRITE_PREPROCESS          PluginType.QUERY_PREPROCESS    │
│       │                                      │                       │
│       ▼                                      ▼                       │
│  WritePreprocessPluginInterface    QueryPreprocessPluginInterface    │
│       │                                      │                       │
│       │  preprocess(text, ctx)              │  preprocess(text, ctx) │
│       │  ctx: WriteContext                  │  ctx: QueryContext     │
│       │  → str                              │  → str                 │
│       │                                      │                       │
│       ▼                                      ▼                       │
│  WritePipeline                      QueryEngine                      │
│  Stage ①                            Stage ①                          │
│                                                                      │
│  多接口插件：                                                         │
│  class UniversalPreprocess(WritePreprocessPluginInterface,           │
│                            QueryPreprocessPluginInterface):          │
│      def get_types(self) -> {WRITE_PREPROCESS, QUERY_PREPROCESS}     │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

## 接口设计

### WritePreprocessPluginInterface

```python
# mcs/interfaces/write_preprocess_plugin.py

from __future__ import annotations
from abc import abstractmethod
from typing import TYPE_CHECKING

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.write_pipeline import WriteContext


class WritePreprocessPluginInterface(Plugin):
    """写入管线前置处理器：preprocess(text, ctx) -> str。

    挂载点：写入管线阶段 ①（幂等检查、摘要生成、文本清洗等）。

    链中的插件串行执行；每个插件的输出成为下一个插件的输入。
    输入/输出类型均为 str，确保链式调用类型安全。

    短路：插件可设置 ctx.skip = True 以终止整个 ingest。
    """

    def get_type(self) -> PluginType:
        return PluginType.WRITE_PREPROCESS

    def execute(self, **kwargs) -> str:
        """统一入口，委托给 preprocess()。"""
        return self.preprocess(
            text=kwargs["text"],
            ctx=kwargs.get("ctx"),
        )

    @abstractmethod
    def preprocess(self, text: str, ctx: WriteContext) -> str:
        """预处理文本并返回处理后的结果。

        返回值必须是 str 类型。
        设置 ctx.skip = True 可短路写入管线。
        """
        pass
```

### QueryPreprocessPluginInterface

```python
# mcs/interfaces/query_preprocess_plugin.py

from __future__ import annotations
from abc import abstractmethod
from typing import TYPE_CHECKING

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.query_engine import QueryContext


class QueryPreprocessPluginInterface(Plugin):
    """查询管线前置处理器：preprocess(text, ctx) -> str。

    挂载点：查询管线阶段 ①（查询改写、同义词扩展、意图识别等）。

    链中的插件串行执行；每个插件的输出成为下一个插件的输入。
    输入/输出类型均为 str，确保链式调用类型安全。
    """

    def get_type(self) -> PluginType:
        return PluginType.QUERY_PREPROCESS

    def execute(self, **kwargs) -> str:
        """统一入口，委托给 preprocess()。"""
        return self.preprocess(
            text=kwargs["text"],
            ctx=kwargs.get("ctx"),
        )

    @abstractmethod
    def preprocess(self, text: str, ctx: QueryContext) -> str:
        """预处理查询文本并返回处理后的结果。

        返回值必须是 str 类型。
        """
        pass
```

## PluginType 枚举变更

```python
# mcs/core/plugin.py

class PluginType(str, Enum):
    ENTRY = "entry"
    TRIM = "trim"
    ARBITRATION = "arbitration"
    POSTPROCESS = "postprocess"

    # 新增：拆分后的前置处理类型
    WRITE_PREPROCESS = "write_preprocess"
    QUERY_PREPROCESS = "query_preprocess"

    # 废弃别名（一个版本后移除）
    PREPROCESS = "write_preprocess"  # 兼容旧代码

    COMPACTION = "compaction"
    INDEX = "index"
    LLM = "llm"
    NODE_EXTENSION = "node_extension"
    STORAGE_SCHEMA_EXT = "storage_schema_ext"
    MAINTENANCE = "maintenance"
```

## 管线调用变更

### WritePipeline._run_preprocess

```python
def _run_preprocess(self, text: str, ctx: WriteContext) -> str:
    """阶段 ①：串行 WritePreprocessPlugin 链。"""
    from mcs.core.plugin import PluginType

    plugins = self.plugin_manager.get_all(PluginType.WRITE_PREPROCESS)
    result: Any = text
    for plugin in plugins:
        result = plugin.preprocess(result, ctx)
        if ctx.skip:
            return result if isinstance(result, str) else text
    return result if isinstance(result, str) else text
```

### QueryEngine._run_preprocess

```python
def _run_preprocess(self, text: str, ctx: QueryContext) -> str:
    """阶段 ①：串行 QueryPreprocessPlugin 链。"""
    from mcs.core.plugin import PluginType

    plugins = self.plugin_manager.get_all(PluginType.QUERY_PREPROCESS)
    if not plugins:
        return text
    result: Any = text
    for plugin in plugins:
        result = plugin.preprocess(result, ctx)
    return result if isinstance(result, str) else text
```

## 插件迁移

### IdempotencyCheckPlugin

```python
# mcs/plugins/phase1/source_tracking.py

from mcs.interfaces.write_preprocess_plugin import WritePreprocessPluginInterface

class IdempotencyCheckPlugin(WritePreprocessPluginInterface):
    """写入阶段 ① 的幂等性检查。"""

    def get_name(self) -> str:
        return "idempotency_check"

    def preprocess(self, text: str, ctx: WriteContext) -> str:
        # 类型安全的 ctx 访问，无需 getattr
        metadata = ctx.metadata
        doc_id = metadata.get("doc_id")
        chunk_id = metadata.get("chunk_id")
        if not (doc_id and chunk_id):
            return text

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if self._already_ingested(doc_id, chunk_id, content_hash):
            ctx.skip = True
            return text

        section_title = metadata.get("section_title")
        metadata["_pending_source"] = Source(
            doc_id=doc_id,
            chunk_id=chunk_id,
            content_hash=content_hash,
            section_title=section_title,
        )
        return text
```

## 向后兼容

1. **废弃别名**：`PluginType.PREPROCESS` 指向 `WRITE_PREPROCESS`，旧代码仍能工作
2. **旧接口保留**：`PreprocessPluginInterface` 作为 `WritePreprocessPluginInterface` 的别名，一个版本后移除
3. **日志警告**：首次使用废弃别名时发出 `DeprecationWarning`

```python
# mcs/interfaces/preprocess_plugin.py（废弃兼容层）

import warnings
from mcs.interfaces.write_preprocess_plugin import WritePreprocessPluginInterface

warnings.warn(
    "PreprocessPluginInterface is deprecated. "
    "Use WritePreprocessPluginInterface or QueryPreprocessPluginInterface instead.",
    DeprecationWarning,
    stacklevel=2,
)

PreprocessPluginInterface = WritePreprocessPluginInterface
```

## 测试策略

| 测试文件                  | 测试内容                                              |
|---------------------------|-------------------------------------------------------|
| `test_plugin_chains.py`   | 新增 `WRITE_PREPROCESS` / `QUERY_PREPROCESS` 类型测试 |
| `test_pipeline_write.py`  | 验证写管线使用 `WRITE_PREPROCESS`                     |
| `test_pipeline_query.py`  | 验证查询管线使用 `QUERY_PREPROCESS`                   |
| 新增废弃测试              | 验证 `PREPROCESS` 别名仍工作 + 发出警告               |

## 风险与缓解

| 风险                         | 缓解措施                                              |
|------------------------------|-------------------------------------------------------|
| 旧插件未迁移                 | 废弃别名 + DeprecationWarning，一个版本缓冲期         |
| 多接口插件组合复杂度         | 文档示例 + `get_types()` 已有模式                     |
| 测试覆盖不足                 | 新增类型隔离测试 + 管线调用测试                       |
