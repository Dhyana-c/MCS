"""记忆 agent 的 ReAct loop。

agent 自有 LLM（独立于 MCS 的 read_llm），经 tool calling 调导航工具（learn / search /
associate / reason / recall）。**导航决策权交给 LLM**：LLM 决定查什么、用哪个种子、
用哪种扩展模式、选哪两个节点找路径。LLM 后端实现 ``AgentLLMInterface``（裸 callable
经 ``CallableAgentLLM`` 自动适配，保既有注入式测试零改动）。

工具集由 ``ToolSpec`` 注册表（``BUILTIN_TOOLS``）驱动、经 ``ToolsetConfig`` 可配置；
``MemoryAgent`` 构造时 ``build_toolset`` 产 ``(schemas, dispatch)``。``_dispatch`` 为
包装层（timing + try/except + ``ToolCallTrace``），按 ``dispatch_table`` 分发，删旧硬编码 if/elif。

消息与工具格式遵循 openai chat completions（deepseek 等 openai 兼容后端通用）。
``AssistantMessage.trace``（``LLMCallTrace``）为一等字段；``chat()`` 读取 trace 后把消息
重建为 openai assistant dict（含完整 ``tool_calls`` 结构）追加到 messages。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from mcs_agent.llms import AgentLLMInterface, CallableAgentLLM
from mcs_agent.tools import BUILTIN_TOOLS, MEMORY_TOOLS, ToolsetConfig, build_toolset
from mcs_agent.trace import ChatTrace, LLMCallTrace, ToolCallTrace

logger = logging.getLogger(__name__)

__all__ = ["MemoryAgent", "DEFAULT_SYSTEM_PROMPT", "MEMORY_TOOLS"]


DEFAULT_SYSTEM_PROMPT = (
    "# 角色\n"
    "你是一个记忆导航助手。你的记忆是一张持续生长的概念图（由 learn 写入）。\n"
    "对用户的问题，先判断「这需要查我的记忆图吗」，再决定直接作答还是用工具探索。\n\n"
    "# 何时直接回答（不调工具）\n"
    "满足任一即直接作答，不要为了「用工具」而用工具：\n"
    "- 闲聊、问候、身份询问（「你好」「你是谁」）。\n"
    "- 通用知识、常识、推理、计算、写作等不依赖个人记忆的内容——用你自身能力照常答。\n"
    "- 你已有的能力足以准确作答。\n\n"
    "# 何时探索记忆图（调工具）\n"
    "只有当问题依赖「已经记下来的东西」——用户曾 learn 过、或图里存着的事实/关系——\n"
    "才进图探索。典型：用户问「我之前记的 X」「那个和 Y 有关吗」。\n\n"
    "# 工具（导航决策权在你：选哪个工具、哪个种子、哪种模式、哪两个节点）\n"
    "- search：搜索入口种子。mode=keyword 按用户输入字面匹配（主力，已实现）；"
    "mode=direct 返回顶层 hub（无明确关键词时用，已实现）；mode=vector 未实现。\n"
    "- associate：从种子联想扩展（BFS）。mode=mcs 已实现（主力）；hot、random 未实现。\n"
    "- reason：在两个已知节点间找连通路径（允许失败）。\n"
    "- recall：回忆最近发生的事件（按时间倒排），回答「最近记了什么/最近有什么」。\n"
    "- learn：把信息写入记忆图（仅当用户明确要记住时）。\n"
    "工具返回的节点带 [id:...]，后续工具用它引用。未实现的模式会返回提示，改用可用项。\n\n"
    "# 探索策略（避免空转）\n"
    "先把相关记忆探索充分再作答；但 search 返回(无)或 associate 无相关时，\n"
    "不要无限换关键词重试——最多换 1-2 种切入（如 keyword 失败改 direct 看顶层 hub），\n"
    "仍无果则据实说明「记忆里没有相关内容」，不要臆造。\n\n"
    "# 记忆诚实\n"
    "- 对依赖记忆的问题：宁可说「记忆里没有」，也不要凭模型知识冒充图里的内容。\n"
    "- 对通用知识：正常答即可。\n"
    "- 关于上文：你只看本轮对话。用户若引用之前聊过的内容，请他重述或明确 learn，"
    "不要假装记得本轮之前的话。\n\n"
    "# learn 边界\n"
    "仅在用户明确表达「记住/记一下/存一下」等写入意图时调用 learn。\n"
    "日常陈述（如「我最近在学 Rust」）若非明确要求记住，则不写图，正常回应即可。"
)


class MemoryAgent:
    """ReAct 记忆 agent。LLM 经 tool calling 调导航工具探索记忆图。

    Args:
        memory: 暴露 learn/search/associate/find_path/recall 的对象（通常是 ``MemoryStore``）。
        llm: ``(messages, tools) -> dict`` 裸 callable（自动包 ``CallableAgentLLM``）或 ``AgentLLMInterface`` 后端。
        tools: 工具集配置（启用子集 / 覆盖参数）；None = 全部 5 个内置工具。
        system_prompt: 系统提示词。
        max_turns: 单次 chat 的最大 LLM 轮次（防失控循环）。
        summary_budget: 注入 system prompt 的图摘要字符预算（第二道闸，防归纳超标进入上下文）。
        on_trace: ``chat()`` 完成后的追踪回调（接收 ``ChatTrace``），None 则不回调。
    """

    def __init__(
        self,
        memory: Any,
        llm: Callable[[list[dict], list[dict]], dict] | AgentLLMInterface,
        *,
        tools: ToolsetConfig | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_turns: int = 8,
        summary_budget: int = 1000,
        on_trace: Callable[[ChatTrace], None] | None = None,
    ) -> None:
        self.memory = memory
        # 裸 callable 自动包 CallableAgentLLM（保既有注入式测试零改动）；AgentLLMInterface 直用
        self.llm: AgentLLMInterface = (
            llm if isinstance(llm, AgentLLMInterface) else CallableAgentLLM(llm)
        )
        # 工具集：build_toolset 产 (schemas_for_llm, dispatch)；tools=None → 全 5 内置
        self.schemas, self.dispatch = build_toolset(BUILTIN_TOOLS, tools)
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.summary_budget = summary_budget
        self.on_trace = on_trace

    def chat(self, user_message: str) -> str:
        """跑一轮 ReAct：LLM 决定调工具或给最终答案，返回最终答复文本。

        每轮注入最新图级摘要进 system prompt（「当前记忆图主题」段），使路由判断有据。
        """
        t_start = time.perf_counter()
        llm_traces: list[LLMCallTrace] = []
        tool_traces: list[ToolCallTrace] = []

        messages: list[dict] = [
            {"role": "system", "content": self._build_system(self._fetch_summary())},
            {"role": "user", "content": user_message},
        ]
        reply = ""
        for _ in range(self.max_turns):
            assistant = self.llm.chat(messages, self.schemas)  # -> AssistantMessage

            # trace 为一等字段（替旧 dict["_trace"] hack）
            if isinstance(assistant.trace, LLMCallTrace):
                llm_traces.append(assistant.trace)

            # 重建 openai assistant dict 后 append：tool_calls 保完整结构（id/type/function）
            # 供后续 tool 消息按 id 配对、openai 多轮回放校验通过；无工具调用时省略 tool_calls。
            entry: dict = {"role": "assistant", "content": assistant.content}
            if assistant.tool_calls:
                entry["tool_calls"] = assistant.tool_calls
            messages.append(entry)

            tool_calls = assistant.tool_calls
            if not tool_calls:
                reply = assistant.content or ""
                break
            for tool_call in tool_calls:
                result, tc_trace = self._dispatch(tool_call)
                if tc_trace is not None:
                    tool_traces.append(tc_trace)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "content": result,
                    }
                )
        else:
            reply = "（达到最大轮次，未能给出最终答复。）"

        # 构造 ChatTrace 并回调
        total_latency_ms = (time.perf_counter() - t_start) * 1000
        chat_trace = ChatTrace(
            user_message=user_message[:100],
            reply=reply[:200],
            llm_calls=llm_traces,
            tool_calls=tool_traces,
            total_latency_ms=total_latency_ms,
        )

        if self.on_trace is not None:
            try:
                self.on_trace(chat_trace)
            except Exception:
                logger.warning("on_trace callback failed", exc_info=True)

        return reply

    def _fetch_summary(self) -> str:
        """取图级摘要；memory 无 ``graph_summary`` 或调用异常时返回空串（不阻塞 chat）。"""
        graph_summary = getattr(self.memory, "graph_summary", None)
        if not callable(graph_summary):
            return ""
        try:
            return graph_summary() or ""
        except Exception:
            logger.warning("取图摘要失败，降级为空", exc_info=True)
            return ""

    def _build_system(self, summary: str) -> str:
        """拼接 system prompt + 「当前记忆图主题」段；摘要超标截断、空则占位。"""
        text = (summary or "").strip()
        if len(text) > self.summary_budget:
            text = text[: self.summary_budget]
        theme = text if text else "(尚未生成)"
        return f"{self.system_prompt}\n\n# 当前记忆图主题\n{theme}"

    def _dispatch(self, tool_call: dict) -> tuple[str, ToolCallTrace | None]:
        """执行单个工具调用，返回 (结果文本, ToolCallTrace | None)。

        包装层：JSON 解析、按 ``self.dispatch`` 分发、timing、异常隔离（``[error]`` 文本）。
        ``handler`` 纯（不做 trace/异常）；本层把 LLM 入参与 ``ToolsetConfig.params`` 合并
        （``{**llm_args, **params}``，params 覆盖同名入参）后调 ``handler(memory, merged)``。
        未知工具 / 非法 JSON / 工具异常均隔离为 ``[error]`` 文本，不抛出。
        """
        fn = tool_call.get("function", {})
        name = fn.get("name", "")
        raw_args = fn.get("arguments", "{}")

        args_summary = (
            raw_args[:200]
            if isinstance(raw_args, str)
            else json.dumps(raw_args, ensure_ascii=False)[:200]
        )

        t0 = time.perf_counter()
        error: str | None = None
        result: str

        # 1) 解析 JSON 参数
        try:
            llm_args = (
                json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            )
        except json.JSONDecodeError:
            latency_ms = (time.perf_counter() - t0) * 1000
            error = "工具参数不是合法 JSON"
            result = f"[error] {error}"
            return result, ToolCallTrace(
                tool_name=name,
                args_summary=args_summary,
                result_summary=result[:200],
                latency_ms=latency_ms,
                error=error,
            )

        # 2) 查 dispatch_table（未知工具）
        entry = self.dispatch.get(name)
        if entry is None:
            latency_ms = (time.perf_counter() - t0) * 1000
            error = f"未知工具：{name}"
            result = f"[error] {error}"
            return result, ToolCallTrace(
                tool_name=name,
                args_summary=args_summary,
                result_summary=result[:200],
                latency_ms=latency_ms,
                error=error,
            )

        # 3) 调 handler（params 覆盖 LLM 同名入参）；异常隔离为 [error]
        handler, params = entry
        try:
            result = handler(self.memory, {**llm_args, **params})
        except Exception as exc:  # 单次工具异常隔离，loop 不崩
            logger.warning("tool %s failed", name, exc_info=True)
            error = f"{type(exc).__name__}: {exc}"
            result = f"[error] {error}"

        latency_ms = (time.perf_counter() - t0) * 1000
        trace = ToolCallTrace(
            tool_name=name,
            args_summary=args_summary,
            result_summary=result[:200],
            latency_ms=latency_ms,
            error=error,
        )
        return result, trace
