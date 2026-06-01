"""OllamaLLMPlugin - 本地 Ollama LLM 后端 (OpenAI 兼容端点)。

实现统一的 ``LLMInterface``。厂商特定的部分仅是
``_raw_call(system, user) -> str``；其余所有内容（渲染、
提示词组装、解析）均由 ``LLMInterface`` 的基类实现处理。

配置键：
  - ``base_url``  (默认: ``"http://localhost:11434/v1"``)
  - ``model``     (如 ``"qwen2.5:7b"``/``"qwen3:8b"``，需先 ``ollama pull``)
  - ``timeout``   (默认: 120 秒，本地推理较慢)
  - ``max_tokens`` (默认: 4096)
  - ``api_key``   (dummy 占位，本地无需鉴权)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar

from mcs.core.errors import LLMCallError
from mcs.interfaces.llm import LLMInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginContext

THINK_START = "<think>"
THINK_END = "</think>"


class OllamaLLMPlugin(Plugin, LLMInterface):
    """通过 Ollama OpenAI 兼容端点的本地 LLM 后端。"""

    name: ClassVar[str] = "ollama_llm"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [LLMInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.base_url: str = self.config.get(
            "base_url", "http://localhost:11434/v1"
        )
        self.model: str = self.config.get("model", "")
        self.timeout: float = float(self.config.get("timeout", 120.0))
        self.max_tokens: int = int(self.config.get("max_tokens", 4096))
        self.api_key: str = self.config.get("api_key", "ollama")
        self.client: Any = None

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        self.attach_renderer(context.context_renderer)
        try:
            from openai import OpenAI  # type: ignore[import]

            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )
        except ImportError:
            self.client = None

    def shutdown(self) -> None:
        self.client = None

    # === LLMInterface ===

    def _raw_call(self, system: str, user: str) -> str:
        if self.client is None:
            raise LLMCallError(
                "Ollama 客户端未初始化；请安装 ``openai`` SDK。"
            )
        if not self.model:
            raise LLMCallError(
                "Ollama 未配置 model；请在 plugin_configs['ollama_llm']['model'] "
                "指定模型（如 'qwen2.5:7b'），并先用 ``ollama pull <model>`` 拉取。"
            )
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": user})
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, max_tokens=self.max_tokens
            )
            msg = resp.choices[0].message
            content = msg.content or ""

            # Qwen3 thinking 模式：content 为空但 reasoning 有内容
            if not content.strip():
                for attr in ("reasoning", "thinking", "reasoning_content"):
                    val = getattr(msg, attr, None) or ""
                    if val and isinstance(val, str):
                        content = self._extract_json_from_thinking(val)
                        break

            # 剥离 <think>...</think> 标签
            content = self._strip_thinking_tags(content)
            return content
        except Exception as e:
            msg = str(e)
            hint = ""
            if "connection" in msg.lower() or "refused" in msg.lower():
                hint = "Ollama 服务未运行；请先执行 ``ollama serve``。"
            elif "404" in msg or "not found" in msg.lower():
                hint = f"模型 '{self.model}' 未拉取；请先执行 ``ollama pull {self.model}``。"
            else:
                hint = "检查 Ollama 服务是否运行、模型是否已拉取。"
            raise LLMCallError(
                f"Ollama call failed: {e}\n提示: {hint}"
            ) from e

    @staticmethod
    def _strip_thinking_tags(content: str) -> str:
        """剥离 <think>...</think> 标签。"""
        return re.sub(rf'^{re.escape(THINK_START)}.*?{re.escape(THINK_END)}\s*',
                       '', content, flags=re.DOTALL)

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
