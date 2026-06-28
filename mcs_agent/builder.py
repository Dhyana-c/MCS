"""记忆 agent 的构造体系：``AgentConfig`` + ``AgentBuilder`` + ``create_agent`` 工厂。

编程式（kwargs）与 YAML（``AgentConfig.from_file``）双路径构造 ``MemoryAgent``（**不**
返回 FastAPI app；``create_app(agent)`` 仍是独立一层）。

**统一 LLM**（design D4/D6/D7）：单一 ``LLMConfig``（provider/model/api_key/base_url/
auth_token）同时驱动 agent 的 chat LLM（经 ``AGENT_LLM_REGISTRY`` 选 adapter）与 MCS 的
write/read LLM（经 ``PROVIDER_TO_MCS_LLM`` 映射插件，``plugin_configs`` key = 完整插件名
``f"{provider}_llm"``）。``mcs_config``（完整 MCSConfig）作逃逸口优先——想给 MCS 配不同
LLM 时用它（此时 agent chat LLM 仍取 ``llm``）。

详见 change ``memory-agent-builder`` 的 design.md（D6 resolve 顺序、P1–P6 厘清）。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Callable

from mcs.entities.config import MCSConfig
from mcs.presets import Phase1Builder, create_mcs

from mcs_agent.llms import AGENT_LLM_REGISTRY, AgentLLMInterface, PROVIDER_TO_MCS_LLM
from mcs_agent.loop import DEFAULT_SYSTEM_PROMPT, MemoryAgent
from mcs_agent.memory import MemoryStore
from mcs_agent.tools import ToolsetConfig
from mcs_agent.trace import ChatTrace

__all__ = [
    "LLMConfig",
    "AgentConfig",
    "AgentBuilder",
    "create_agent",
]

# provider → 默认 base_url（LLMConfig.base_url 为 None 时填，agent + MCS 共用同源）。
# deepseek / ollama 走 openai SDK，其 base_url 默认连官方 api.openai.com——必须注入 provider
# 端点，否则 agent 后端连错；claude 走 anthropic SDK（默认即 api.anthropic.com），注入为显式同源。
_PROVIDER_DEFAULT_BASE_URL: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "ollama": "http://localhost:11434/v1",
    "claude": "https://api.anthropic.com",
}


@dataclass
class LLMConfig:
    """统一 LLM 配置（喂 agent adapter + MCS 插件）。

    Attributes:
        provider: ``"deepseek"`` | ``"ollama"`` | ``"claude"``（须在 ``AGENT_LLM_REGISTRY``；
            官方 openai 无 MCS 插件、不作统一 provider 键）。
        model: 模型名。
        api_key: API 密钥（openai-compat / claude x-api-key）。
        base_url: 端点；None → provider 默认（见 ``_PROVIDER_DEFAULT_BASE_URL``）。
        auth_token: 仅 claude：Bearer 授权（claude_llm 优先于 api_key）；非 claude 忽略。
    """

    provider: str
    model: str
    api_key: str = ""
    base_url: str | None = None
    auth_token: str | None = None


@dataclass
class AgentConfig:
    """记忆 agent 的配置对象。

    Attributes:
        llm: 统一 LLM；缺则 ``build()`` 报错（agent chat 无后端，mcs_config 的 LLM 无
            tool-calling 救不了）。
        mcs_config: 完整 MCSConfig（逃逸口，优先；自带 MCS LLM）。与 db_path 同给则覆盖其
            sqlite path。
        db_path: 存储路径（统一 llm 走 create_mcs 时用；加载已有 db 数据由 SQLiteStore 自动完成）。
        tools: 工具集配置（启用子集 / 覆盖参数）；默认全部 7 个内置。
        max_turns: 单次 chat 最大 LLM 轮次。
        summary_budget: 注入 system prompt 的图摘要字符预算。
        system_prompt: 系统提示词。
        on_trace: ``chat()`` 完成后的追踪回调（接收 ``ChatTrace``）。
    """

    llm: LLMConfig | None = None
    mcs_config: MCSConfig | None = None
    db_path: str | None = None
    tools: ToolsetConfig = field(default_factory=ToolsetConfig)
    max_turns: int = 8
    summary_budget: int = 1000
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    on_trace: Callable[[ChatTrace], None] | None = None

    @classmethod
    def from_file(cls, path: str) -> "AgentConfig":
        """从 YAML 加载 AgentConfig。

        YAML 承载：统一 ``llm``（含可选 ``auth_token``）+ 可选 ``mcs_config``（**指向独立
        mcs.yaml 的路径**，惰性调 ``MCSConfig.from_file`` 解析，复用其 preset/overlay/
        env_expand，不在 agent.yaml 重实现 MCSConfig 解析）+ db_path / tools / max_turns 等。
        ``on_trace`` 不从文件读（callable 不可序列化）。
        """
        try:
            import yaml  # 惰性 import（缺失报安装指引）
        except ImportError as exc:  # pragma: no cover - 环境依赖
            raise ImportError(
                "PyYAML 未安装；AgentConfig.from_file 需要 `pip install pyyaml`"
            ) from exc

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        llm_data = data.get("llm")
        if llm_data:
            # provider 为 LLMConfig 必填；缺则给清晰早失败（而非裸 TypeError: missing 'provider'）
            if not llm_data.get("provider"):
                raise ValueError(
                    "agent.yaml 的 llm 段缺 provider（须为 deepseek / ollama / claude）"
                )
            llm = LLMConfig(**llm_data)
        else:
            llm = None

        mcs_path = data.get("mcs_config")
        mcs_config = MCSConfig.from_file(mcs_path) if mcs_path else None

        tools_data = data.get("tools") or {}
        tools = ToolsetConfig(
            enabled=tools_data.get("enabled"),
            params=tools_data.get("params") or {},
        )

        return cls(
            llm=llm,
            mcs_config=mcs_config,
            db_path=data.get("db_path"),
            tools=tools,
            max_turns=data.get("max_turns", 8),
            summary_budget=data.get("summary_budget", 1000),
            system_prompt=data.get("system_prompt") or DEFAULT_SYSTEM_PROMPT,
        )


class AgentBuilder:
    """按 ``AgentConfig`` 构造 ``MemoryAgent``（见 design D6 resolve 顺序）。"""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def build(self) -> MemoryAgent:
        cfg = self.config

        # 步骤 0：前置校验（两条独立判据，任一命中即清晰报错）
        if cfg.llm is None:
            raise ValueError(
                "agent chat 无 LLM 后端：AgentConfig.llm 缺失"
                "（mcs_config 的 LLM 无 tool-calling，不能作 agent chat 后端）"
            )
        if cfg.llm.provider not in AGENT_LLM_REGISTRY:
            raise ValueError(
                f"未知 LLM provider: {cfg.llm.provider!r}；"
                f"可用: {sorted(AGENT_LLM_REGISTRY)}"
            )
        if cfg.mcs_config is None and cfg.db_path is None:
            raise ValueError("无图谱来源：AgentConfig 需 db_path 或 mcs_config")

        # 步骤 1：定 build_fn（决定 MCS 来源）
        build_fn = self._build_fn(cfg)

        # 步骤 2：memory（build_fn 在单 worker 线程内执行，SQLite 线程亲和不破）
        memory = MemoryStore(build_fn)

        # 步骤 3：llm_backend（llm 已校验非 None；callable 适配不在 builder，在 MemoryAgent.__init__）
        llm = cfg.llm
        base_url = llm.base_url or _PROVIDER_DEFAULT_BASE_URL.get(llm.provider)
        backend_cls = AGENT_LLM_REGISTRY[llm.provider]
        llm_backend: AgentLLMInterface = backend_cls(
            llm.model, api_key=llm.api_key, base_url=base_url, auth_token=llm.auth_token
        )

        # 步骤 4：return MemoryAgent
        return MemoryAgent(
            memory,
            llm_backend,
            tools=cfg.tools,
            system_prompt=cfg.system_prompt,
            max_turns=cfg.max_turns,
            summary_budget=cfg.summary_budget,
            on_trace=cfg.on_trace,
        )

    @staticmethod
    def _with_db_path(mcs_config: MCSConfig, db_path: str | None) -> MCSConfig:
        """返回 sqlite path 覆盖后的 mcs_config（**不污染原对象**）。

        用 ``dataclasses.replace`` 重建：浅拷贝 plugin_configs 顶层 + 新建 sqlite_storage
        内层 dict（setdefault 语义防空 key）。勿就地改 / 勿 deepcopy（mcs_config 含
        Callable parser 字段，deepcopy 会炸）。
        """
        if db_path is None:
            return mcs_config
        pc = dict(mcs_config.plugin_configs)
        pc["sqlite_storage"] = {**pc.get("sqlite_storage", {}), "path": db_path}
        return dataclasses.replace(mcs_config, plugin_configs=pc)

    def _build_fn(self, cfg: AgentConfig) -> Callable[[], object]:
        """按 resolve 顺序定 MCS build_fn（mcs_config 优先，否则统一 llm 走 create_mcs）。"""
        if cfg.mcs_config is not None:
            mcs_config = self._with_db_path(cfg.mcs_config, cfg.db_path)

            def build_fn(_cfg: MCSConfig = mcs_config) -> object:
                return Phase1Builder(_cfg).build()

            return build_fn

        # 统一 llm 走 create_mcs（llm 已校验非 None，mcs_config is None ⇒ db_path 非 None）
        llm = cfg.llm
        assert llm is not None  # 步骤 0 已保证（type checker 收窄）
        provider_short = PROVIDER_TO_MCS_LLM[llm.provider]
        plugin_key = f"{provider_short}_llm"  # ⚠️ 完整插件名，非 provider 键（design D6 警告）
        base_url = llm.base_url or _PROVIDER_DEFAULT_BASE_URL.get(llm.provider)
        seed: dict = {"model": llm.model, "api_key": llm.api_key, "base_url": base_url}
        if llm.provider == "claude" and llm.auth_token is not None:
            seed["auth_token"] = llm.auth_token

        db_path = cfg.db_path

        def build_fn(
            _short: str = provider_short,
            _db: str | None = db_path,
            _key: str = plugin_key,
            _seed: dict = seed,
        ) -> object:
            return create_mcs(llm=_short, db_path=_db, plugin_configs={_key: _seed})

        return build_fn


def create_agent(
    *,
    db_path: str | None = None,
    llm_provider: str | None = None,
    llm_api_key: str = "",
    llm_model: str | None = None,
    llm_base_url: str | None = None,
    llm_auth_token: str | None = None,
    mcs_config: MCSConfig | None = None,
    tools: ToolsetConfig | None = None,
    max_turns: int = 8,
    summary_budget: int = 1000,
    system_prompt: str | None = None,
    on_trace: Callable[[ChatTrace], None] | None = None,
) -> MemoryAgent:
    """工厂：编程式构造 ``MemoryAgent``（单一 LLM 配置喂 agent + MCS）。

    见 design D7。``llm_provider=None`` ⇒ ``llm=None`` ⇒ ``build()`` 报错（除非另给
    ``mcs_config``，但 agent chat 仍需 ``llm``）。
    """
    llm = (
        LLMConfig(
            provider=llm_provider,
            model=llm_model or "",
            api_key=llm_api_key,
            base_url=llm_base_url,
            auth_token=llm_auth_token,
        )
        if llm_provider is not None
        else None
    )
    config = AgentConfig(
        llm=llm,
        mcs_config=mcs_config,
        db_path=db_path,
        tools=tools or ToolsetConfig(),
        max_turns=max_turns,
        summary_budget=summary_budget,
        system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
        on_trace=on_trace,
    )
    return AgentBuilder(config).build()
