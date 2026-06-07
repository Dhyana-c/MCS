"""插件基类与类型枚举。

所有 MCS 插件的顶级抽象，定义插件必须实现的核心方法。
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class PluginType(str, Enum):
    """MCS 插件类型枚举。

    继承 str 和 Enum，使得：
    - 可作为 dict key（str 可哈希）
    - 支持字符串比较：PluginType.ENTRY == "entry"
    - 支持枚举语法：PluginType.ENTRY
    """

    ENTRY = "entry"
    TRIM = "trim"
    ARBITRATION = "arbitration"
    POSTPROCESS = "postprocess"
    COMPACTION = "compaction"
    INDEX = "index"
    LLM = "llm"
    NODE_EXTENSION = "node_extension"
    STORAGE_SCHEMA_EXT = "storage_schema_ext"
    MAINTENANCE = "maintenance"


class Plugin(ABC):
    """所有 MCS 插件的顶级基类。

    设计原则：
    - 使用实例方法而非 ClassVar，支持运行时动态配置
    - execute() 作为统一入口，便于管线统一调用
    - initialize/shutdown 管理生命周期
    """

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}

    @abstractmethod
    def get_name(self) -> str:
        """返回插件标识符。

        用于日志、配置索引、node.extensions 键名（NodeExtension 插件）。
        """
        pass

    @abstractmethod
    def get_type(self) -> PluginType:
        """返回插件类型。

        用于 PluginManager 按类型索引和查找。
        """
        pass

    def get_types(self) -> set[PluginType]:
        """返回插件实现的全部类型（用于多接口插件的索引）。

        默认返回 ``{get_type()}``。同时实现多个接口的插件
        （如 SourceTracking 既是 NodeExtension 又是 StorageSchemaExtension）
        应覆写此方法返回其全部类型，使 PluginManager 能按每个类型索引到它。
        """
        return {self.get_type()}

    def get_priority(self) -> int:
        """返回执行优先级（数值越大越优先）。

        默认返回 0。子类可覆写。
        用于 EntryPlugin 等需要排序的场景。
        """
        return 0

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """统一执行入口。

        管线可通过此方法统一调用任意插件。
        具体语义由各接口定义。
        """
        pass

    def initialize(self, context: Any) -> None:
        """初始化插件。

        默认空操作。子类可覆写以访问 graph/config 等。
        """
        pass

    def shutdown(self) -> None:
        """清理插件资源。

        默认空操作。子类可覆写。
        """
        pass
