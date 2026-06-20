"""MCS 配置。

参见 openspec/specs/phase1-defaults/spec.md 了解默认插件集约定和参数默认值。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mcs.utils.env_expand import expand_env
from mcs.utils.imports import import_from_path

# ── Phase1 默认插件分配 ──────────────────────────────────────────────────
# 参见 openspec/specs/mcs-presets/spec.md "Phase1 默认插件分配"

PHASE1_SHARED_PLUGINS: list[str] = [
    "source_tracking",     # NodeExtension + StorageSchemaExt
    "summary",             # NodeExtension
]

PHASE1_WRITE_PLUGINS: list[str] = [
    "idempotency_check",   # Postprocess (write_preprocess)
    "fanout_reducer",      # Compaction
    "summary_regen",       # Compaction
    "graph_summary",       # Compaction（图级主题摘要，learn 后归纳顶层 hub；须在 fanout 后跑）
]

PHASE1_READ_PLUGINS: list[str] = [
    "alias_index",         # Index
    "alias_entry",         # Entry (priority=100)
    "hub_fallback",        # Entry (priority=0)
    "priority_trim",       # Trim
]

# 旧名保留（向后兼容别名，供 openspec 等引用）
PHASE1_DEFAULT_PLUGINS: list[str] = PHASE1_SHARED_PLUGINS + PHASE1_WRITE_PLUGINS + PHASE1_READ_PLUGINS


@dataclass
class MCSConfig:
    """MCS 顶级配置。

    ``prompt_overrides`` 的键是 LLM 目的（如 ``"extract_concepts"``），值是部分包
    ``{"system": str?, "template": str?, "parser": Callable?}``。未提供的组件将回退到
    ``mcs.prompts.DEFAULT_PROMPTS`` 中注册的第一阶段默认值。
    """

    mode: str = "knowledge_graph"
    token_budget: int = 8000
    max_rounds: int = 5
    max_accumulated_nodes: int = 1000
    auto_persist: bool = True

    # 分离配置（替代旧 plugins 字段）
    shared_plugins: list[str] = field(default_factory=list)   # Graph/Storage/NodeExtension
    write_plugins: list[str] = field(default_factory=list)    # Compaction/write Postprocess
    read_plugins: list[str] = field(default_factory=list)     # Entry/Trim/Index/read Postprocess

    # LLM 分离
    write_llm: str = ""   # 写入 LLM 名称
    read_llm: str = ""    # 读取 LLM 名称

    plugin_configs: dict = field(default_factory=dict)
    prompt_overrides: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def knowledge_graph(
        cls,
        write_llm: str = "deepseek",
        read_llm: str | None = None,
    ) -> MCSConfig:
        """第一阶段默认配置：shared+write+read 插件分离，T=8000，max_rounds=5，max_accumulated_nodes=1000。

        ``write_llm`` / ``read_llm`` 选择厂商 LLM 后端：

          - ``"deepseek"``（默认）：使用 ``deepseek_llm``
          - ``"claude"``：使用 ``claude_llm``
          - ``"ollama"``：使用 ``ollama_llm``

        若 ``read_llm`` 未指定，则与 ``write_llm`` 相同（共用同一 LLM）。

        参见 phase1-defaults 与 claude-llm-adapter capability spec。
        """
        if read_llm is None:
            read_llm = write_llm

        # 验证 LLM 名称
        valid_llms = {"deepseek", "claude", "ollama"}
        if write_llm not in valid_llms:
            raise ValueError(
                f"unknown write_llm={write_llm!r}; expected 'deepseek', 'claude', or 'ollama'"
            )
        if read_llm not in valid_llms:
            raise ValueError(
                f"unknown read_llm={read_llm!r}; expected 'deepseek', 'claude', or 'ollama'"
            )

        # 生成 LLM 插件名称
        write_llm_name = f"{write_llm}_llm"
        read_llm_name = f"{read_llm}_llm"

        # 构建 plugin_configs
        plugin_configs: dict = {
            "sqlite_storage": {"path": "mcs.db"},
        }
        _add_llm_config(plugin_configs, write_llm, write_llm_name)
        if read_llm_name != write_llm_name:
            _add_llm_config(plugin_configs, read_llm, read_llm_name)

        return cls(
            mode="knowledge_graph",
            token_budget=8000,
            max_rounds=5,
            max_accumulated_nodes=1000,
            shared_plugins=list(PHASE1_SHARED_PLUGINS),
            write_plugins=list(PHASE1_WRITE_PLUGINS),
            read_plugins=list(PHASE1_READ_PLUGINS),
            write_llm=write_llm_name,
            read_llm=read_llm_name,
            plugin_configs=plugin_configs,
        )

    @classmethod
    def memory_system(cls) -> MCSConfig:
        """第二阶段默认配置（占位符；第二阶段插件尚未实现）。
        相同的第一阶段基础 + 6 个覆盖插件。
        """
        return cls(
            mode="memory_system",
            token_budget=8000,
            max_rounds=5,
            max_accumulated_nodes=1000,
            shared_plugins=list(PHASE1_SHARED_PLUGINS),
            write_plugins=list(PHASE1_WRITE_PLUGINS),
            read_plugins=list(PHASE1_READ_PLUGINS),
            write_llm="deepseek_llm",
            read_llm="deepseek_llm",
        )

    @classmethod
    def from_file(cls, path: str) -> MCSConfig:
        """从 YAML 文件加载 MCSConfig（纯新增，既有构造路径逐字不变）。

        算法：惰性 ``import yaml``（缺失报 ``pip install mcs[yaml]``）→ 解析 →
        ``expand_env`` 展开 ``${VAR}`` → 若有 ``preset`` 键则调对应 preset 工厂铺底、
        否则以 ``MCSConfig()`` 默认为底 → 用其余字段叠加 → 返回。

        叠加规则（见 openspec/changes/config-file-loading/design.md D1）：
          - 标量字段覆盖；
          - ``shared_plugins`` / ``write_plugins`` / ``read_plugins`` 显式给出则**替换**、
            否则保留底；
          - ``plugin_configs`` 按插件名**两层深合并**（底的 ``model`` 与文件的 ``api_key`` 共存）；
          - ``prompt_overrides`` 按 purpose 合并；``parser`` 为 import-path 串时解析为 Callable；
          - 有 ``preset`` 时 ``write_llm`` / ``read_llm`` **仅作工厂参数
            消费、不再二次叠加**（否则把工厂产出的 ``deepseek_llm`` 覆盖回短名 ``deepseek``）。

        Args:
            path: YAML 配置文件路径。

        Returns:
            与手写形状一致的 MCSConfig。

        Raises:
            ImportError: 缺 PyYAML（信息含 ``pip install mcs[yaml]``）。
            FileNotFoundError: 配置文件不存在。
            yaml.YAMLError: YAML 解析失败。
            EnvExpansionError: ``${VAR}`` 引用的环境变量未设置。
            ValueError: 未知 preset / 根非 mapping。
        """
        data = cls._load_yaml(path)
        data = expand_env(data)
        preset = data.pop("preset", None)

        if preset is not None:
            base = cls._build_preset_base(preset, data)
        else:
            base = cls()

        cls._apply_overlay(base, data, preset_consumed=preset is not None)
        return base

    @staticmethod
    def _load_yaml(path: str) -> dict:
        """惰性加载并解析 YAML（PyYAML 缺失报含安装指引的错误）。"""
        try:
            import yaml
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required to load YAML config. "
                "Install it with: pip install mcs[yaml]"
            ) from exc
        with open(path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ValueError(
                f"config root must be a mapping, got {type(loaded).__name__}"
            )
        return loaded

    @classmethod
    def _build_preset_base(cls, preset: str, data: dict) -> MCSConfig:
        """调 preset 工厂铺底；消费 write_llm / read_llm（不二次叠加）。"""
        if preset == "knowledge_graph":
            return cls.knowledge_graph(
                write_llm=data.pop("write_llm", "deepseek"),
                read_llm=data.pop("read_llm", None),
            )
        if preset == "memory_system":
            # memory_system() 不接受 LLM 参数；消费这两个键以免被当字段二次叠加。
            data.pop("write_llm", None)
            data.pop("read_llm", None)
            return cls.memory_system()
        raise ValueError(
            f"unknown preset {preset!r}; expected 'knowledge_graph' or 'memory_system'"
        )

    @classmethod
    def _apply_overlay(
        cls, base: MCSConfig, data: dict, *, preset_consumed: bool
    ) -> None:
        """把 data 中剩余字段叠加到 base（就地修改）。

        Args:
            base: preset 工厂产出或 MCSConfig() 默认底。
            data: 经 expand_env 处理、已弹出 preset（及 preset 分支消费的 LLM 两键）后的字段。
            preset_consumed: 是否已用 preset（True 时 write_llm/read_llm 已消费、
                不再当字段叠加）。
        """
        scalar_fields = (
            "mode",
            "token_budget",
            "max_rounds",
            "max_accumulated_nodes",
            "auto_persist",
        )
        for field_name in scalar_fields:
            if field_name in data:
                setattr(base, field_name, data[field_name])

        # LLM 原始字段：仅无 preset 时叠加。
        if not preset_consumed:
            if "write_llm" in data:
                base.write_llm = data["write_llm"]
            if "read_llm" in data:
                base.read_llm = data["read_llm"]

        # 插件列表：显式给出则替换、否则留底。
        for plist in ("shared_plugins", "write_plugins", "read_plugins"):
            if plist in data:
                setattr(base, plist, list(data[plist]))

        # plugin_configs：按插件名两层深合并。
        if "plugin_configs" in data:
            _deep_merge_plugin_configs(base.plugin_configs, data["plugin_configs"])

        # prompt_overrides：按 purpose 合并；parser import-path 串 → Callable。
        if "prompt_overrides" in data:
            _merge_prompt_overrides(base.prompt_overrides, data["prompt_overrides"])


def _deep_merge_plugin_configs(target: dict, overlay: dict) -> None:
    """按插件名两层深合并：外层按插件名、内层合并该插件 dict 的键（就地修改 target）。

    使 preset 的 ``{model: ...}`` 与文件的 ``{api_key: ...}`` 共存（非整体替换）。
    """
    for name, cfg in overlay.items():
        if (
            name in target
            and isinstance(target.get(name), dict)
            and isinstance(cfg, dict)
        ):
            merged = dict(target[name])
            merged.update(cfg)
            target[name] = merged
        else:
            target[name] = cfg


def _merge_prompt_overrides(target: dict, overlay: dict) -> None:
    """按 purpose 合并 prompt_overrides；parser 为 import-path 串时解析为 Callable（就地修改 target）。

    ``system`` / ``template`` 保持文本；``parser`` 若为字符串则视为 import-path 解析为
    可调用对象，与 ``MCSConfig`` 内存形状（parser 为 Callable）一致。
    """
    for purpose, overrides in overlay.items():
        merged = dict(target.get(purpose, {}))
        merged.update(overrides)
        if "parser" in merged and isinstance(merged["parser"], str):
            merged["parser"] = import_from_path(merged["parser"])
        target[purpose] = merged


def _add_llm_config(plugin_configs: dict, llm: str, llm_name: str) -> None:
    """向 plugin_configs 添加指定 LLM 的默认配置。"""
    if llm == "deepseek":
        plugin_configs[llm_name] = {"api_key": "", "model": "deepseek-chat"}
    elif llm == "claude":
        plugin_configs[llm_name] = {
            "auth_token": "",
            "model": "claude-3-5-sonnet-latest",
            "base_url": "https://api.anthropic.com",
        }
    elif llm == "ollama":
        plugin_configs[llm_name] = {
            "model": "",
            "base_url": "http://localhost:11434/v1",
            # 思维模型（qwen3/qwq/deepseek-r1…）默认关闭 thinking：
            # MCS 只取结构化 JSON，thinking 纯属浪费且会把调用拖到分钟级。
            "think": False,
        }
