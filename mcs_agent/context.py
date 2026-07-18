"""agent 会话上下文自治（OpenSpec change agent-context-autonomy）。

框架保证单一硬 ``context_budget``（会话层铁律一：估算口径 == 发送口径——对将要发送
的每条消息取同一份文本计 token，MUST NOT 交给 LLM 自估）；预算内的取舍（pin / 换出 /
重看 / 收尾）全部交模型自决策。默认关闭：``MemoryAgent(context_budget=None)`` 不建本
类实例，loop 走原路径零行为变化。

机制（design D2-D6）：

- **存根折叠**（D2）：距当前 ≥ N 轮且未 pin 的工具结果 → 单行存根（工具名 + 参数摘要 +
  触达节点 id）。id 来源选定为**解析工具返回文本的 ``[id:...]``**（``ToolCallTrace.
  result_summary`` 截断 200 字符拿不到全量 id）。id **窗口级去重**：首见全文列出、已见
  计数省略；每轮从原始 history 重算视图（幂等），**原始 history 永不改写**——折叠 / 逐出
  都是组装期的视图操作，被折叠内容随时可经 pin 恢复全文或按 id 取回。
- **重复调用不拦截**（D2）：同工具同参的再次调用正常执行，仅在结果头部标注
  「与存根 #k 同参」——去重做成信号不做成机制（相关性判断是积累集依赖的，learn 会改图）。
- **确定性兜底**（D3）：超预算 → ①按轮龄折叠 → ②全量折叠未 pin 项 → ③逐出最旧未 pin
  存根——实现为一行墓碑 ``[已逐出 #k]`` 而非物理删除（openai 格式要求 assistant 的每个
  tool_call 有配对 tool 消息）→ ④仍超：标记 exhausted、降级发送（MUST NOT 静默截断中段 /
  死锁），本轮新工具调用不执行、以 [预算耗尽] tool 消息告知模型换出或收尾。
- **pin / FINISH**（D4/D6）：模型以回复文本标记声明（``PIN: #k`` / ``UNPIN: #k`` /
  ``FINISH`` + ``USED: #k``），框架解析——不新增工具、不占轮次。pin 总量有防御上限
  （默认预算 70%）。FINISH 宽松解析：无标记且无工具调用仍接受为最终答复（记 implicit）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from mcs.core.calibrated_estimator import CalibratedEstimator
from mcs_agent.trace import ContextEvent

__all__ = ["SessionContext", "CONTEXT_MANAGEMENT_PROMPT"]

_ID_RE = re.compile(r"\[id:([^\]\s]+)\]")
_PIN_RE = re.compile(r"^\s*(PIN|UNPIN):\s*(.+?)\s*$", re.MULTILINE)
_FINISH_RE = re.compile(r"^\s*FINISH\s*$", re.MULTILINE)
_USED_RE = re.compile(r"^\s*USED:\s*(.+?)\s*$", re.MULTILINE)
_REF_RE = re.compile(r"#\d+|\[id:[^\]\s]+\]")
# 管理标记行（PIN/UNPIN/USED/FINISH）从最终答复剥离
_MARKER_LINE_RE = re.compile(r"^\s*(?:(?:PIN|UNPIN|USED):.*|FINISH)\s*$\n?", re.MULTILINE)

REFUSAL_MESSAGE = (
    "[预算耗尽] 新工具结果未注入（本次调用未执行）。"
    "请用 UNPIN: #k 换出不再需要的 pin 项，或用 FINISH 收尾作答。"
)

CONTEXT_MANAGEMENT_PROMPT = (
    "# 会话上下文管理（预算开启）\n"
    "- 较早的工具结果会折叠为一行存根「[已折叠 #k] 工具(参数) → [id:...]」；"
    "细节可按 [id:...] 经 associate 等取回，或直接 PIN: #k 恢复该存根全文（遗忘可逆）。\n"
    "- 确认某结果支撑最终答案时，在回复末尾单独一行 `PIN: #k`（可多个，空格分隔）"
    "钉住防折叠；不再需要时 `UNPIN: #k` 换出。探索性结果不要 pin。\n"
    "- 判断无需再探索、可以作答时，在最终回复末尾单独一行 `FINISH`，"
    "下一行 `USED: #k` 引用支撑答案的存根编号或节点 id。\n"
    "- 「与存根 #k 同参」表示该调用此前发过：仅当积累的上下文已变化、值得重看时才重发。\n"
    "- 收到 [预算耗尽] 时：UNPIN 换出不需要的项，或直接 FINISH 收尾。"
)


@dataclass
class _ToolRecord:
    """一条工具结果消息的簿记（存根候选）。history 只增不删，hist_idx 稳定。"""

    stub_no: int  # 1-based 存根编号（#k）
    hist_idx: int  # 在原始 history 中的下标
    tool_name: str
    args_key: str  # 同参检测键（空串 = 不参与同参匹配，如拒绝注入消息）
    args_brief: str  # 存根里展示的参数摘要
    node_ids: list[str]  # 结果文本解析出的全量 [id:...]（去重保序）
    turn: int  # 结果产生的轮次
    result_head: str  # 无 id 时存根展示的结果开头
    # 本记录创建时的 pin 集快照（stub_no 集合）——同参重发时对比：无变化 = 盲目重复
    # （A/B「盲目重复率」的数据源；积累集变化后的有意重看不算震荡）
    pin_snapshot: frozenset = frozenset()
    pinned: bool = False
    evicted: bool = False
    # 受保护：不折叠不逐出。[预算耗尽] 告知消息用——若可被兜底链折叠/逐出，
    # 极端超预算时模型永远看不到「请换出或收尾」的指引（消息本身 ~40 token、受 max_turns 有界）。
    protected: bool = False
    fold_logged: bool = field(default=False, repr=False)  # 首折已记 trace（防逐轮重复）


class SessionContext:
    """单次 chat 的会话上下文自治状态机（folding / pin / 兜底 / 终止解析）。

    loop 每轮调 ``assemble`` 取发送视图；工具结果经 ``register_result`` 注册簿记
    （同参标注在此发生）；assistant 文本经 ``apply_pins`` / ``parse_finish`` 解析标记。
    """

    def __init__(
        self,
        budget: int,
        *,
        fold_after_turns: int = 2,
        pin_cap_ratio: float = 0.7,
        count_tokens: Callable[[str], int] | None = None,
    ) -> None:
        self.budget = budget
        self.fold_after_turns = fold_after_turns
        self.pin_cap_ratio = pin_cap_ratio
        # 默认保守估算（宁高估勿低估——低估漏判破坏硬闸）；可注入精确计数
        self.count = count_tokens or CalibratedEstimator("unknown").estimate
        self.records: list[_ToolRecord] = []
        self._by_hist_idx: dict[int, _ToolRecord] = {}
        self.events: list[ContextEvent] = []
        self.exhausted = False  # 兜底链④：本轮拒绝注入新工具结果
        self._turn = 0
        self._last_estimate = 0

    # ── 注册与标注 ──────────────────────────────────────────────

    def register_result(self, result: str, tool_call: dict, hist_idx: int, turn: int) -> str:
        """注册一条工具结果（存根候选），返回（可能带同参标注的）注入文本。"""
        fn = tool_call.get("function", {})
        name = fn.get("name", "")
        raw = fn.get("arguments", "")
        brief = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        brief = brief.replace("\n", " ")[:60]
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
            key = f"{name}|{json.dumps(parsed, sort_keys=True, ensure_ascii=False)}"
        except (json.JSONDecodeError, TypeError):
            key = f"{name}|{raw}"

        # 同参标注：匹配窗口内（未逐出）最近一条同键存根——只标注，不拦截不缓存
        dup = next(
            (r for r in reversed(self.records) if r.args_key == key and not r.evicted),
            None,
        )
        annotated = f"（与存根 #{dup.stub_no} 同参）\n{result}" if dup else result
        pins_now = frozenset(r.stub_no for r in self.records if r.pinned and not r.evicted)
        if dup is not None:
            # 盲目重复 = 同参重发且 pin 集自上次该调用以来无变化（有意重看不算震荡）
            blind = pins_now == dup.pin_snapshot
            self.events.append(
                ContextEvent(
                    kind="dup_call",
                    stub_no=dup.stub_no,
                    detail=f"{name}({brief}) pin集{'未变' if blind else '已变'}",
                )
            )

        ids = list(dict.fromkeys(_ID_RE.findall(result)))
        head = result.replace("\n", " ")[:50]
        rec = _ToolRecord(
            stub_no=len(self.records) + 1,
            hist_idx=hist_idx,
            tool_name=name,
            args_key=key,
            args_brief=brief,
            node_ids=ids,
            turn=turn,
            result_head=head,
            pin_snapshot=pins_now,
        )
        self.records.append(rec)
        self._by_hist_idx[hist_idx] = rec
        return annotated

    def refuse(self, tool_call: dict, hist_idx: int, turn: int) -> str:
        """预算耗尽：不执行工具，注册并返回 [预算耗尽] 告知消息（受保护、不参与同参匹配）。"""
        fn = tool_call.get("function", {})
        name = fn.get("name", "")
        brief = str(fn.get("arguments", ""))[:60]
        rec = _ToolRecord(
            stub_no=len(self.records) + 1,
            hist_idx=hist_idx,
            tool_name=name,
            args_key="",
            args_brief=brief,
            node_ids=[],
            turn=turn,
            result_head="[预算耗尽]",
            protected=True,
        )
        self.records.append(rec)
        self._by_hist_idx[hist_idx] = rec
        self.events.append(
            ContextEvent(kind="reject", stub_no=rec.stub_no, detail=f"{name}({brief})")
        )
        return REFUSAL_MESSAGE

    # ── 标记解析（pin / FINISH）──────────────────────────────────

    def apply_pins(self, content: str, history: list[dict]) -> None:
        """解析 assistant 文本中的 PIN/UNPIN 标记并应用（含防御上限检查）。"""
        cap = self.budget * self.pin_cap_ratio
        for m in _PIN_RE.finditer(content):
            verb = m.group(1)
            nos = [int(x) for x in re.findall(r"#(\d+)", m.group(2))]
            for no in nos:
                rec = next(
                    (r for r in self.records if r.stub_no == no and not r.evicted), None
                )
                if rec is None:
                    continue  # 幻觉编号 / 已逐出：忽略
                if verb == "UNPIN":
                    if rec.pinned:
                        rec.pinned = False
                        self.events.append(ContextEvent(kind="unpin", stub_no=no))
                    continue
                if rec.pinned:
                    continue
                cost = self.count(history[rec.hist_idx].get("content") or "")
                if self._pinned_tokens(history) + cost > cap:
                    self.events.append(
                        ContextEvent(
                            kind="pin_rejected",
                            stub_no=no,
                            detail=f"超防御上限 {int(cap)} token",
                            tokens_before=cost,
                        )
                    )
                    continue
                rec.pinned = True
                self.events.append(ContextEvent(kind="pin", stub_no=no))

    def parse_finish(self, content: str) -> tuple[str, str, list[str]]:
        """解析最终答复：返回（剥离管理标记后的答复, 终止类型, USED 引用列表）。

        FINISH 命中 → ``finish``；否则 ``implicit``（宽松接受，不为格式合规浪费轮次）。
        引用提取两级：规范 ``USED:`` 行优先（模型按相关性排过序的显式声明，不掺入
        散落提及）；无规范行时**宽松提取**终止回复中出现的全部 ``[id:...]``（按出现序
        去重）——答案里引用的 id 就是它用到的证据，把格式采纳率变成实际上限。
        """
        finished = bool(_FINISH_RE.search(content))
        used: list[str] = []
        for m in _USED_RE.finditer(content):
            used.extend(_REF_RE.findall(m.group(1)))
        if not used:
            used = [f"[id:{i}]" for i in dict.fromkeys(_ID_RE.findall(content))]
        clean = _MARKER_LINE_RE.sub("", content).strip()
        return clean, ("finish" if finished else "implicit"), used

    # ── 组装（硬闸 + 兜底链）────────────────────────────────────

    def assemble(
        self, history: list[dict], turn: int, max_turns: int, *, finalize: bool = False
    ) -> list[dict]:
        """组装本轮发送视图：折叠 → 超预算兜底链 → 注入预算段。估算口径 == 发送口径。

        ``finalize=True`` 为收尾轮（轮次耗尽后的有界 +1 调用）：预算段替换为
        「立即交付最终答案」硬指令；剩余 1 轮时预算段也带最后一轮收尾指令（D5）。
        """
        self._turn = turn
        left = 0 if finalize else max_turns - turn
        view, est = self._render(history, left, emergency=False, finalize=finalize)
        if est > self.budget:
            view, est = self._render(history, left, emergency=True, finalize=finalize)
            while est > self.budget:
                victim = next(
                    (r for r in self.records if not r.pinned and not r.evicted and not r.protected),
                    None,
                )
                if victim is None:
                    break
                victim.evicted = True
                self.events.append(
                    ContextEvent(
                        kind="evict",
                        stub_no=victim.stub_no,
                        detail=f"{victim.tool_name}({victim.args_brief})",
                    )
                )
                view, est = self._render(history, left, emergency=True, finalize=finalize)
        # 折叠 + 逐出全部用尽仍超（pin + 不可折叠底座 > 预算）：降级发送、拒绝后续注入。
        # MUST NOT 静默截断消息中段 / MUST NOT 死锁。
        was_exhausted = self.exhausted
        self.exhausted = est > self.budget
        if self.exhausted and not was_exhausted:
            self.events.append(
                ContextEvent(kind="overflow", detail=f"折叠+逐出后仍超预算：{est}/{self.budget}")
            )
        self._last_estimate = est
        return view

    def _render(
        self, history: list[dict], turns_left: int, *, emergency: bool, finalize: bool = False
    ) -> tuple[list[dict], int]:
        """按当前簿记渲染视图并估算总量（同一文本计 token——铁律一）。

        窗口级 id 去重在渲染期按存根时序计算：已逐出存根不占坑（其 id 已出窗，
        同 id 在后续存根重新首见），保证「窗口内尚未出现的 id 不丢」。
        """
        seen_ids: set[str] = set()
        view: list[dict] = []
        for idx, msg in enumerate(history):
            rec = self._by_hist_idx.get(idx)
            if rec is None:  # system / user / assistant：不折叠
                view.append(msg)
                continue
            if rec.evicted:
                view.append({**msg, "content": f"[已逐出 #{rec.stub_no}]"})
                continue
            foldable = (
                not rec.pinned
                and not rec.protected
                and (emergency or self._turn - rec.turn >= self.fold_after_turns)
            )
            if not foldable:
                view.append(msg)
                continue
            stub = self._stub_line(rec, seen_ids)
            # 优化判据：总量不降的重组无效——存根不比全文短就不折（短结果保全文更省且信息更全）
            if self.count(stub) >= self.count(msg.get("content") or ""):
                view.append(msg)
                continue
            seen_ids.update(rec.node_ids)
            if not rec.fold_logged:
                rec.fold_logged = True
                self.events.append(
                    ContextEvent(
                        kind="fold",
                        stub_no=rec.stub_no,
                        detail=f"{rec.tool_name}({rec.args_brief})",
                        tokens_before=self.count(msg.get("content") or ""),
                        tokens_after=self.count(stub),
                    )
                )
            view.append({**msg, "content": stub})
        base = sum(self.count(_message_text(m)) for m in view)
        if finalize:
            # 收尾轮：轮次已尽仍未作答，硬指令立即交付（forced 从无答案失败降级为降级交付）
            budget_section = (
                "\n\n# 会话预算\n轮次已尽。这是收尾轮：立即基于已有结果输出最终答案，"
                "并以 `USED:` 列出支撑引用；不要再调用工具（工具调用将被忽略）。"
            )
        elif turns_left <= 1:
            budget_section = (
                f"\n\n# 会话预算\n已用约 {base}/{self.budget} token，这是最后一轮："
                f"请直接输出最终答案 + `USED:` 支撑引用（FINISH 收尾），不要再调用工具。"
            )
        else:
            budget_section = (
                f"\n\n# 会话预算\n已用约 {base}/{self.budget} token，剩余轮次 {turns_left}。"
                f"预算或轮次将尽时，基于已 pin 的结果用 FINISH 收尾作答。"
            )
        view[0] = {**view[0], "content": (view[0].get("content") or "") + budget_section}
        # 预算段插入后按最终视图重算（估算 == 发送口径：发送什么就估什么，不做分段近似）
        est = sum(self.count(_message_text(m)) for m in view)
        return view, est

    def _stub_line(self, rec: _ToolRecord, seen_ids: set[str]) -> str:
        new_ids = [i for i in rec.node_ids if i not in seen_ids]
        if rec.node_ids:
            shown = ", ".join(f"[id:{i}]" for i in new_ids) or "(均已见)"
            dup = len(rec.node_ids) - len(new_ids)
            body = f"{len(rec.node_ids)} 节点: {shown}" + (f" (+{dup} 已见)" if dup else "")
        else:
            body = rec.result_head or "(无节点)"
        return f"[已折叠 #{rec.stub_no}] {rec.tool_name}({rec.args_brief}) → {body}"

    def _pinned_tokens(self, history: list[dict]) -> int:
        return sum(
            self.count(history[r.hist_idx].get("content") or "")
            for r in self.records
            if r.pinned and not r.evicted
        )


def _message_text(msg: dict) -> str:
    """一条消息的估算文本：content + 工具调用的 name/arguments（发送口径的全部可变字段）。"""
    text = msg.get("content") or ""
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        args = fn.get("arguments", "")
        if not isinstance(args, str):
            args = json.dumps(args, ensure_ascii=False)
        text += "\n" + fn.get("name", "") + args
    return text
