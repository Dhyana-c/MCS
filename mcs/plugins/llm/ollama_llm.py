"""OllamaLLMPlugin - 本地/远程 Ollama LLM 后端（原生 ``/api/chat`` 端点）。

实现统一的 ``LLMInterface``。厂商特定的部分仅是
``_raw_call(system, user) -> str``；其余所有内容（渲染、
提示词组装、解析）均由 ``LLMInterface`` 的基类实现处理。

走 Ollama **原生** ``/api/chat`` 而非 OpenAI 兼容 ``/v1`` 端点：只有原生端点
支持 ``think`` 开关，能对 qwen3/qwq/deepseek-r1 等"思维模型"关闭冗长的
chain-of-thought。MCS 只需要结构化 JSON，thinking 纯属浪费且会把单次调用从
秒级拖到分钟级——关掉它是 Ollama 后端可用的前提。

配置键：
  - ``base_url``  (默认: ``"http://localhost:11434/v1"``；末尾 ``/v1`` 会被自动
    归一为根地址，因此与旧配置兼容)
  - ``model``     (如 ``"qwen3.5:9b"``，需先 ``ollama pull``)
  - ``timeout``   (默认: 120 秒，本地推理较慢)
  - ``max_tokens`` (默认: 32768，映射到 ``options.num_predict``)
  - ``num_ctx``   (默认: 8192，映射到 ``options.num_ctx``，避免长文档块被默认
    上下文窗口静默截断)
  - ``think``     (默认: False，思维模型关闭 thinking)
  - ``api_key``   (默认占位 ``"ollama"``；非占位时作为 Bearer 头发出，支持带鉴权的远程代理)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from mcs.core.errors import LLMCallError
from mcs.interfaces.llm import LLMInterface

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginContext

THINK_START = "<think>"
THINK_END = "</think>"


class OllamaLLMPlugin(LLMInterface):
    """通过 Ollama 原生 ``/api/chat`` 端点的本地/远程 LLM 后端。"""

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.base_url: str = self.config.get(
            "base_url", "http://localhost:11434/v1"
        )
        self.model: str = self.config.get("model", "")
        self.timeout: float = float(self.config.get("timeout", 120.0))
        self.max_tokens: int = int(self.config.get("max_tokens", 32768))
        self.num_ctx: int = int(self.config.get("num_ctx", 8192))
        self.think: bool = bool(self.config.get("think", False))
        self.api_key: str = self.config.get("api_key", "ollama")
        self.client: Any = None

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "ollama_llm"

    # 注：LLMInterface 已提供 get_type() 和 execute()，无需重写

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        self.attach_renderer(context.context_renderer)
        try:
            import httpx  # type: ignore[import]

            headers: dict[str, str] = {}
            if self.api_key and self.api_key != "ollama":
                headers["Authorization"] = f"Bearer {self.api_key}"
            self.client = httpx.Client(timeout=self.timeout, headers=headers)
        except ImportError:
            self.client = None

    def shutdown(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
        self.client = None

    @property
    def chat_url(self) -> str:
        """由 ``base_url`` 推导原生 chat 端点：归一掉末尾 ``/v1`` 再拼 ``/api/chat``。"""
        root = self.base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3].rstrip("/")
        return f"{root}/api/chat"

    # === LLMInterface ===

    def _raw_call(self, system: str, user: str) -> str:
        return self._call_with_retry(self._do_raw_call, system, user)

    def _do_raw_call(self, system: str, user: str) -> str:
        if self.client is None:
            raise LLMCallError(
                "Ollama 客户端未初始化；请安装 ``httpx``。"
            )
        if not self.model:
            raise LLMCallError(
                "Ollama 未配置 model；请在 plugin_configs['ollama_llm']['model'] "
                "指定模型（如 'qwen3.5:9b'），并先用 ``ollama pull <model>`` 拉取。"
            )

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": self.think,
            "options": {
                "num_predict": self.max_tokens,
                "num_ctx": self.num_ctx,
            },
        }

        try:
            resp = self.client.post(self.chat_url, json=payload)
        except Exception as e:
            raise LLMCallError(
                f"Ollama 连接失败: {e}\n"
                "提示: Ollama 服务未运行或地址不可达；请确认 ``ollama serve`` "
                "已启动、base_url 正确。",
                retryable=True,
            ) from e

        if resp.status_code >= 400:
            body = (resp.text or "")[:300]
            # 429 / 5xx 为可重试错误
            retryable = resp.status_code == 429 or resp.status_code >= 500
            if resp.status_code == 404 or "not found" in body.lower():
                hint = (
                    f"模型 '{self.model}' 未拉取；请先执行 "
                    f"``ollama pull {self.model}``。"
                )
            else:
                hint = "检查 Ollama 服务是否运行、模型是否已拉取。"
            raise LLMCallError(
                f"Ollama call failed: HTTP {resp.status_code} {body}\n提示: {hint}",
                retryable=retryable,
            )

        data = resp.json()
        msg = data.get("message") or {}
        content = msg.get("content") or ""

        # think 模式：content 为空但 thinking 字段有内容时，从思考文本中兜底提取 JSON
        if not content.strip():
            thinking = msg.get("thinking") or ""
            if thinking and isinstance(thinking, str):
                content = self._extract_json_from_thinking(thinking)

        # 剥离内联 thinking 标签（部分模型把思考写进 content）
        content = self._strip_thinking_tags(content)
        return content

    @staticmethod
    def _strip_thinking_tags(content: str) -> str:
        """剥离前导思考片段。

        覆盖两种形态：
          1. 成对的 thinking markers；
          2. 仅有闭合 marker 的残留（think=False 下模型偶尔把无开标签的
             思考写进正文）——截到第一个闭合 marker 之后。
        """
        content = re.sub(
            rf'^\s*{re.escape(THINK_START)}.*?{re.escape(THINK_END)}\s*',
            '', content, flags=re.DOTALL,
        )
        if THINK_END in content:
            content = content.split(THINK_END, 1)[1].lstrip()
        return content

    @staticmethod
    def _extract_json_from_thinking(text: str) -> str:
        """从 thinking/reasoning 文本中提取 JSON 输出。

        thinking 内容通常以思考过程开头，末尾有实际 JSON 输出。
        """
        # 找 JSON 代码块 ```json ... ```
        m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if m:
            return m.group(1).strip()

        # 从后往前找最后一个完整的 JSON 数组或对象
        # 先找最后一个 ] 或 } 的位置
        last_close = -1
        for c in (']', '}'):
            idx = text.rfind(c)
            if idx > last_close:
                last_close = idx

        if last_close > 0:
            # 找对应的起始括号
            close_char = text[last_close]
            open_char = '[' if close_char == ']' else '{'
            depth = 0
            for i in range(last_close, -1, -1):
                if text[i] == close_char:
                    depth += 1
                elif text[i] == open_char:
                    depth -= 1
                    if depth == 0:
                        return text[i:last_close + 1]

        # 找以 [ 或 { 开头的行块
        lines = text.split('\n')
        json_lines = []
        in_json = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(('[', '{')):
                in_json = True
            if in_json:
                json_lines.append(line)
        if json_lines:
            return '\n'.join(json_lines)

        return ""