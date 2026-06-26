"""Anthropic 原生后端（claude）：openai chat-completions ↔ anthropic messages 双向翻译。

agent 内部消息 / 工具格式以 openai chat-completions 为 lingua franca（deepseek / ollama
原生兼容）；本 adapter 在 ``chat()`` 内把整段 openai history 翻译为 anthropic 原生格式
（system 单独参数、assistant tool_use block 化、tool 消息并入 user 的 tool_result block）、
调 anthropic SDK、再把响应翻回 ``AssistantMessage``。

首版仅支持 text + tool_calls 子集（多模态 content 留 TODO，同当前 openai 实现的 NOTE）。
``anthropic`` SDK 在 ``_client()`` 内惰性 import——未装清晰报错，不影响 openai-compat 后端。

授权：``auth_token``（Bearer）优先、回退 ``api_key``（x-api-key），对齐 MCS ``claude_llm``。
"""

from __future__ import annotations

import json
import time

from mcs_agent.llms.base import AgentLLMInterface, AssistantMessage
from mcs_agent.trace import LLMCallTrace, MessageSummary, TokenUsage

# anthropic messages.create 必填 max_tokens；agent chat 用作上限（非 token 预算 T）
_MAX_TOKENS = 4096


class AnthropicAgentLLM(AgentLLMInterface):
    """anthropic 原生 claude 后端。构造接 auth_token / api_key（auth_token 优先）。"""

    def __init__(
        self,
        model: str,
        api_key: str = "",
        base_url: str | None = None,
        auth_token: str | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.auth_token = auth_token
        self._client = None  # 惰性构造后缓存（避免每次 chat 重建）

    def _get_client(self):  # type: ignore[no-untyped-def]
        """惰性 import + 构造并缓存 anthropic client。

        auth_token 优先（Bearer）、否则回退 api_key（x-api-key）——对齐 claude_llm。
        未装 anthropic 时清晰报错（不影响 openai-compat 后端）。
        """
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - 环境依赖
                raise ImportError(
                    "AnthropicAgentLLM 需要 anthropic 包：pip install anthropic"
                    "（或 mcs 的 claude extra）"
                ) from exc
            if self.auth_token:
                self._client = anthropic.Anthropic(
                    auth_token=self.auth_token, base_url=self.base_url
                )
            else:
                self._client = anthropic.Anthropic(
                    api_key=self.api_key, base_url=self.base_url
                )
        return self._client

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
        client = self._get_client()
        wall_time = time.time()
        t0 = time.perf_counter()

        system, anth_msgs = _openai_to_anthropic(messages)
        anth_tools = _openai_tools_to_anthropic(tools)

        kwargs: dict = {
            "model": self.model,
            "messages": anth_msgs,
            "max_tokens": _MAX_TOKENS,
        }
        if system:
            kwargs["system"] = system
        if anth_tools:
            kwargs["tools"] = anth_tools

        resp = client.messages.create(**kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000

        content, tool_calls = _anthropic_to_openai(resp)

        # === trace ===
        usage = getattr(resp, "usage", None)
        token_usage: TokenUsage | None = None
        if usage is not None:
            in_tok = getattr(usage, "input_tokens", None)
            out_tok = getattr(usage, "output_tokens", None)
            total = (in_tok or 0) + (out_tok or 0)
            token_usage = TokenUsage(
                prompt_tokens=in_tok,
                completion_tokens=out_tok,
                total_tokens=total or None,
            )
        request_summary = [
            MessageSummary(role=m.get("role", ""), content_preview=(m.get("content") or "")[:100])
            for m in messages
        ]
        response_summary = (content or "")[:200]
        tool_call_names = [tc["function"]["name"] for tc in tool_calls if tc["function"].get("name")]
        trace = LLMCallTrace(
            model=self.model,
            latency_ms=latency_ms,
            token_usage=token_usage,
            timestamp=wall_time,
            request_summary=request_summary,
            response_summary=response_summary,
            tool_call_names=tool_call_names,
        )
        return AssistantMessage(content=content, tool_calls=tool_calls, trace=trace)


# === 翻译纯函数（可单测，无需 SDK） ===


def _openai_to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """openai messages → (system, anthropic messages)。

    - openai ``system`` 消息 → 合并为 anthropic 的 ``system`` 参数（单串）。
    - ``assistant`` 消息 → ``content`` 文本块 + ``tool_use`` 块（保 id / name / input）。
    - ``tool`` 消息 → 并入紧邻的 ``user`` role ``tool_result`` 块（anthropic 要求 tool_result
      在 user role，且紧跟 assistant tool_use）；无则新建 user。
    - ``user`` 消息 → 原样（content 串）。
    """
    system_parts: list[str] = []
    anth: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            c = m.get("content") or ""
            if c:
                system_parts.append(c)
            continue
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id", ""),
                "content": m.get("content") or "",
            }
            # 并入最近一个 user（若其 content 已是 block list）；否则新建 user
            if anth and anth[-1]["role"] == "user" and isinstance(anth[-1]["content"], list):
                anth[-1]["content"].append(block)
            else:
                anth.append({"role": "user", "content": [block]})
            continue
        if role == "assistant":
            blocks: list[dict] = []
            text = m.get("content")
            if text:
                blocks.append({"type": "text", "text": text})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                try:
                    inp = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    inp = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": inp,
                    }
                )
            anth.append({"role": "assistant", "content": blocks if blocks else (text or "")})
            continue
        # user / 其他：content 串
        anth.append({"role": role or "user", "content": m.get("content") or ""})
    return ("\n\n".join(system_parts) if system_parts else ""), anth


def _openai_tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """openai function tools → anthropic tools（input_schema = parameters）。"""
    out: list[dict] = []
    for t in tools or []:
        fn = t.get("function", {})
        out.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return out


def _anthropic_to_openai(resp) -> tuple[str | None, list[dict]]:  # type: ignore[no-untyped-def]
    """anthropic response → (content, tool_calls)。tool_use 块 → openai tool_calls 结构。"""
    blocks = getattr(resp, "content", []) or []
    texts: list[str] = []
    tool_calls: list[dict] = []
    for b in blocks:
        btype = getattr(b, "type", None)
        if btype == "text":
            texts.append(getattr(b, "text", ""))
        elif btype == "tool_use":
            inp = getattr(b, "input", {}) or {}
            tool_calls.append(
                {
                    "id": getattr(b, "id", ""),
                    "type": "function",
                    "function": {
                        "name": getattr(b, "name", ""),
                        "arguments": json.dumps(inp, ensure_ascii=False),
                    },
                }
            )
    content = "".join(texts) if texts else None
    return content, tool_calls
