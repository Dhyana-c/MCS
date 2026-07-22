"""记忆 agent 的 ReAct loop。

agent 自有 LLM（独立于 MCS 的 read_llm），经 tool calling 调工具（learn / search /
associate / reason / recall / timeline / generalize / arbitrate / split / merge /
get_cross_universe_edges / link_cross_universe）。**导航 / 判断决策权交给 LLM**：LLM 决定查什么、用哪个种子、
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

from mcs_agent.context import CONTEXT_MANAGEMENT_PROMPT, SessionContext
from mcs_agent.llms import AgentLLMInterface, CallableAgentLLM
from mcs_agent.memory import MemoryShuttingDown
from mcs_agent.tools import BUILTIN_TOOLS, MEMORY_TOOLS, ToolsetConfig, build_toolset
from mcs_agent.trace import ChatTrace, LLMCallTrace, ToolCallTrace

logger = logging.getLogger(__name__)

__all__ = ["MemoryAgent", "DEFAULT_SYSTEM_PROMPT", "LANGUAGE_FOLLOW_PROMPT", "MEMORY_TOOLS"]


LANGUAGE_FOLLOW_PROMPT = (
    "# 回答语言\n"
    "始终用**用户消息的语言**回答（英文问全程英文答、中文问中文答）；"
    "记忆图节点内容与用户语言不一致时，引用其信息须**转成用户的语言**转述，不要原文照搬。"
    "若不确定用户使用哪种语言，先据用户消息本身的用词判断再作答（主动对齐），"
    "不要默认用某种语言。"
)


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
    "才进图探索。典型：用户问「我之前记的 X」「那个和 Y 有关吗」。\n"
    "撞见多个相关概念想找它们的共性、或撞见矛盾 / 互斥的说法时，可用 generalize / arbitrate\n"
    "做只读语义判断（不改图）。发觉某概念把多个语义中心耦合（如'按摩'实讲泰式、或'小明和小红'\n"
    "误并），可用 split 拆开；发觉重复 / 同义节点，可用 merge 收口（写图，谨慎）。\n\n"
    "# 工具（导航决策权在你：选哪个工具、哪个种子、哪种模式、哪两个节点）\n"
    "- search：搜索入口种子（默认在现实世界 __reality__ 内；查作品世界时显式传 universe）。"
    "mode=keyword 按用户输入字面匹配（主力，已实现）；"
    "mode=direct 返回顶层 hub（无明确关键词时用，已实现）；mode=vector 未实现。\n"
    "- associate：从种子联想扩展——一跳邻居（关联/互斥端点，含 id），零成本、即时；多跳靠对邻居 id 继续 associate。\n"
    "- reason：在两个已知节点间找连通路径（允许失败）。\n"
    "- recall：回忆最近发生的事件（按时间倒排），回答「最近记了什么/最近有什么」。\n"
    "- timeline：组装某世界的叙事时间线（该世界事件层按时间**升序**，只读），回答"
    "「这部作品的时间线/事件先后」；作品世界传作品名、现实传 __reality__。与 recall 互补。\n"
    "- generalize：概括若干节点的公共上位概念 / 共性，帮你理解一组概念的关系（只读）。\n"
    "- arbitrate：对若干互斥事实反查背书事件、裁决采信哪个 + 理由（只读）。\n"
    "- split：拆分一个粒度耦合的概念节点（content 把类别和特化耦合，或多实体误并）为多个\n"
    "  独立节点（写图）。content 自洽别拆、描述不准是重写不是拆、拿不准别拆。\n"
    "- merge：合并若干本就同一个的节点（异名/同义/重复建）为一个（写图）。\n"
    "  同名异义别合、互斥禁合、拿不准别合。core 已自动合并同义，本工具用于收口残留重复。\n"
    "- get_cross_universe_edges：定向查某节点的跨 universe 桥（只读，绕载重）——"
    "单 universe 查询默认不跨 universe，需确认跨世界关系（如演义曹操↔正史曹操）时用。\n"
    "- link_cross_universe：给两个不同 universe 的节点建概念桥（写图）——仅当判定是"
    "同一实体的不同世界叙述时调；同 universe 勿用（走既有对齐）。\n"
    "- learn：把信息写入记忆图（仅当用户明确要记住时）。\n"
    "工具返回的节点带 [id:...]，后续工具用它引用。generalize / arbitrate / merge 的 node_ids、\n"
    "split 的 node_id 由前序工具返回的 [id:...] 提供。未实现的模式会返回提示，改用可用项。\n\n"
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
        memory: 暴露 learn/search/associate/find_path/recall/generalize/arbitrate 的对象（通常是 ``MemoryStore``）。
        llm: ``(messages, tools) -> dict`` 裸 callable（自动包 ``CallableAgentLLM``）或 ``AgentLLMInterface`` 后端。
        tools: 工具集配置（启用子集 / 覆盖参数）；None = 全部 12 个内置工具。
        system_prompt: 系统提示词。
        max_turns: 单次 chat 的最大 LLM 轮次（防失控循环）。
        summary_budget: 注入 system prompt 的图摘要字符预算（第二道闸，防归纳超标进入上下文）。
        on_trace: ``chat()`` 完成后的追踪回调（接收 ``ChatTrace``），None 则不回调。
        context_budget: 会话级上下文预算（token）。None（默认）= 关闭，行为与现状完全
            一致；开启后每轮组装 messages 经会话上下文自治机制（``mcs_agent.context``：
            存根折叠 / pin / FINISH / 确定性兜底），并注入管理约定与动态预算段。
        fold_after_turns: 工具结果距当前 ≥ N 轮且未 pin 时折叠为存根（预算开启时生效）。
        pin_cap_ratio: pin 总量防御上限占预算比例（防囤积）。
        token_counter: token 估算函数（估算口径 == 发送口径）；None 用保守经验式。
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
        context_budget: int | None = None,
        fold_after_turns: int = 2,
        pin_cap_ratio: float = 0.7,
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        self.memory = memory
        self._shutting_down = False  # B1：记忆关闭中（_dispatch 捕 MemoryShuttingDown 置位）
        # 裸 callable 自动包 CallableAgentLLM（保既有注入式测试零改动）；AgentLLMInterface 直用
        self.llm: AgentLLMInterface = (
            llm if isinstance(llm, AgentLLMInterface) else CallableAgentLLM(llm)
        )
        # 工具集：build_toolset 产 (schemas_for_llm, dispatch)；tools=None → 全 12 内置
        self.schemas, self.dispatch = build_toolset(BUILTIN_TOOLS, tools)
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.summary_budget = summary_budget
        self.on_trace = on_trace
        self.context_budget = context_budget
        self.fold_after_turns = fold_after_turns
        self.pin_cap_ratio = pin_cap_ratio
        self.token_counter = token_counter

    def chat(self, user_message: str) -> str:
        """跑一轮 ReAct：LLM 决定调工具或给最终答案，返回最终答复文本。

        每轮注入最新图级摘要进 system prompt（「当前记忆图主题」段），使路由判断有据。
        开启 ``context_budget`` 时（agent-context-autonomy）：``messages`` 为原始历史
        （只增不改写），每轮经 ``SessionContext.assemble`` 折叠出发送视图并保证 ≤ 预算；
        assistant 文本解析 PIN/UNPIN/FINISH 标记；预算耗尽时新工具调用不执行、以
        [预算耗尽] tool 消息告知模型换出或收尾。
        """
        self._shutting_down = False  # B1：每次 chat 重置（表「本次 chat」状态，防实例级粘性泄漏）
        t_start = time.perf_counter()
        llm_traces: list[LLMCallTrace] = []
        tool_traces: list[ToolCallTrace] = []

        ctx: SessionContext | None = None
        system = self._build_system(self._fetch_summary())
        if self.context_budget is not None:
            ctx = SessionContext(
                self.context_budget,
                fold_after_turns=self.fold_after_turns,
                pin_cap_ratio=self.pin_cap_ratio,
                count_tokens=self.token_counter,
            )
            system = f"{system}\n\n{CONTEXT_MANAGEMENT_PROMPT}"

        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]
        reply = ""
        termination = "implicit"
        used_refs: list[str] = []
        for turn in range(self.max_turns):
            send = ctx.assemble(messages, turn, self.max_turns) if ctx is not None else messages
            try:
                assistant = self.llm.chat(send, self.schemas)  # -> AssistantMessage
            except Exception as exc:
                # LLM 调用失败（网络/限流/鉴权/空 tools 400 等）：优雅降级、仍构造并触发 trace
                logger.warning("agent LLM 调用失败: %s", exc)
                reply = f"（助手暂时不可用：{type(exc).__name__}）"
                termination = "error"
                break

            # trace 为一等字段（替旧 dict["_trace"] hack）
            if isinstance(assistant.trace, LLMCallTrace):
                llm_traces.append(assistant.trace)

            # 重建 openai assistant dict 后 append：tool_calls 保完整结构（id/type/function）
            # 供后续 tool 消息按 id 配对、openai 多轮回放校验通过；无工具调用时省略 tool_calls。
            entry: dict = {"role": "assistant", "content": assistant.content}
            if assistant.tool_calls:
                entry["tool_calls"] = assistant.tool_calls
            messages.append(entry)

            if ctx is not None and assistant.content:
                ctx.apply_pins(assistant.content, messages)

            tool_calls = assistant.tool_calls
            if not tool_calls:
                reply = assistant.content or ""
                if ctx is not None:
                    reply, termination, used_refs = ctx.parse_finish(reply)
                break
            for tool_call in tool_calls:
                if ctx is not None and ctx.exhausted:
                    # 兜底链④：预算耗尽——不执行工具、以 [预算耗尽] 告知（拒绝注入新结果）
                    result = ctx.refuse(tool_call, len(messages), turn)
                else:
                    result, tc_trace = self._dispatch(tool_call)
                    if tc_trace is not None:
                        tool_traces.append(tc_trace)
                    if ctx is not None:
                        result = ctx.register_result(result, tool_call, len(messages), turn)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "content": result,
                    }
                )
                if self._shutting_down:
                    # B1：记忆正在关闭——跳出 tool_call 循环（剩余 tool_calls 不再执行）
                    break
            if self._shutting_down:
                # B1：优雅收尾——不进下一轮 LLM（避免撞下一轮 _submit sentinel 兜成 [error]
                # 空转到 max_turns）。break 跳出 turn 循环，不进 for-else 的 forced 分支。
                reply = "（记忆服务正在关闭，本次对话无法继续。）"
                termination = "shutting_down"
                break
        else:
            reply = "（达到最大轮次，未能给出最终答复。）"
            termination = "forced"
            if ctx is not None:
                # 收尾轮（有界 +1 调用，仅预算开启时）：轮次耗尽仍未作答 → 注入
                # 「立即交付」硬指令再调一次，工具调用被忽略——forced 从「无答案失败」
                # 降级为「降级交付」（termination=finalized）；仍无内容则保持 forced 兜底。
                try:
                    send = ctx.assemble(messages, self.max_turns, self.max_turns, finalize=True)
                    assistant = self.llm.chat(send, self.schemas)
                    if isinstance(assistant.trace, LLMCallTrace):
                        llm_traces.append(assistant.trace)
                    if assistant.content:
                        reply, _, used_refs = ctx.parse_finish(assistant.content)
                        termination = "finalized"
                except Exception as exc:
                    logger.warning("收尾轮 LLM 调用失败: %s", exc)

        # 构造 ChatTrace 并回调
        total_latency_ms = (time.perf_counter() - t_start) * 1000
        chat_trace = ChatTrace(
            user_message=user_message[:100],
            reply=reply[:200],
            llm_calls=llm_traces,
            tool_calls=tool_traces,
            total_latency_ms=total_latency_ms,
            context_events=ctx.events if ctx is not None else [],
            termination=termination,
            used_refs=used_refs,
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
        """拼接 system prompt + 语言跟随规则 + 「当前记忆图主题」段。

        语言跟随追加在**任意** system_prompt（含调用方自定义）之后——记忆图节点
        语言可能与用户语言不一致（如中文抽取产物 vs 英文提问），回答语言以用户为准。
        摘要超标截断、空则占位。
        """
        text = (summary or "").strip()
        if len(text) > self.summary_budget:
            text = text[: self.summary_budget]
        theme = text if text else "(尚未生成)"
        return (
            f"{self.system_prompt}\n\n{LANGUAGE_FOLLOW_PROMPT}"
            f"\n\n# 当前记忆图主题\n{theme}"
        )

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
        except MemoryShuttingDown:
            # B1：记忆正在关闭——置 flag、返回友好降级文本（非 [error]），chat loop 据此
            # 优雅收尾（termination='shutting_down'），而非兜成 [error] 空转到 max_turns。
            self._shutting_down = True
            result = "（记忆服务正在关闭，本次工具调用未完成。）"
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
