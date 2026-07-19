"""LoCoMo 数据三源合成装载（D1）。

以 **V2 base conversation + QA 为唯一主体**（建图语料与评测问题同用 V2 人名），
另移植两样东西到 V2 上：

1. **caption（取 V2 caption 变体，默认 moondream）**：V2 base 无 caption（带图轮
   caption 全空）。V2 仓库另提供 ``locomo_v2_{moondream,qwen,minicpm}.json`` 三个
   VLM caption 变体，其 conversation 文本与 base **逐轮零差异**，caption 按
   ``dia_id`` 直接移植（死链 76 轮保持无 caption）。
2. **evidence（从 V1_source 移植）**：V2 QA 有意删除了 evidence（Multi-Mention
   Flaw）。按**换名映射**（仅由两版 ``speaker_a/b`` 字段机械建立、词边界替换 +
   大小写不敏感精确匹配、**不经 LLM**）把 V1 ``evidence`` 移植到 V2 题，仅作诊断用途。

**关键**（V2 是去污染换名版）：V2 把 10/10 对话人物全部换名（Caroline→Sarah……），
迫使被测系统依赖真实检索。**绝不能混用 V1 问题查 V2 语料建的图**——本装载器
保证问题与图同用 V2 人名。

数据格式细节、换名映射全表见本 change 根目录 ``data-format.md``；决策依据见
``design.md`` D1/D9。
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"
PREPROCESSED_DIR = DATA_DIR / "preprocessed"

# 数据文件规范位置（download_data.py 把 clone 放到 DATA_DIR/locomo_{repo,v2}/）。
DEFAULT_BASE = DATA_DIR / "locomo_v2" / "data" / "locomo_v2_base.json"
DEFAULT_V1_SOURCE = DATA_DIR / "locomo_v2" / "data" / "locomo_v1_source.json"
DEFAULT_CAPTION_DIR = DATA_DIR / "locomo_v2" / "data"

# caption 变体 -> (文件名, 字段名)。
CAPTION_VARIANT_FILE: dict[str, str] = {
    "moondream": "locomo_v2_moondream.json",
    "qwen": "locomo_v2_qwen.json",
    "minicpm": "locomo_v2_minicpm.json",
}
CAPTION_VARIANT_FIELD: dict[str, str] = {
    "moondream": "moondream_caption",
    "qwen": "qwen_caption",
    "minicpm": "minicpm_caption",
}

# LoCoMo 论文时间戳格式（实测 288 会话 0 失败）；locale 无关的手动解析见 parse_timestamp。
TIMESTAMP_FORMAT = "%I:%M %p on %d %B, %Y"

# category int -> 名称（实测钉死，见 D9）。
CATEGORY_NAMES: dict[int, str] = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
    5: "adversarial",
}
# V2 base 类别分布（实测，总 1922）。漂移即数据版本不符，MUST 报错。
EXPECTED_CATEGORY_COUNTS: dict[int, int] = {1: 261, 2: 308, 3: 94, 4: 821, 5: 438}
# moondream caption 覆盖的带图轮数（910 带图轮 - 76 死链 = 834）。
EXPECTED_CAPTION_COUNT = 834
# evidence 移植命中率下限（实测 ~97%，spec 要求 ≥ 95%）。
MIN_EVIDENCE_HIT_RATE = 0.95

_MONTHS: dict[str, int] = {
    m.lower(): i for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"], 1)
}
_TS_RE = re.compile(
    r"^(\d{1,2}):(\d{2})\s*(am|pm)\s+on\s+(\d{1,2})\s+([A-Za-z]+),\s+(\d{4})$",
    re.IGNORECASE,
)
# 答案尾部的标注标签（86 LOCOMO-AUDIT + 3 LOCOMO-ISSUES），计分前剥离。
_AUDIT_RE = re.compile(r"\s*\[(LOCOMO-AUDIT|LOCOMO-ISSUES)\]\s*$")
_DIA_RE = re.compile(r"^D(\d+):(\d+)$")
_SESSION_KEY_RE = re.compile(r"^session_(\d+)$")
_SESSION_TS_KEY_RE = re.compile(r"^session_(\d+)_date_time$")


@dataclass
class LoCoMoTurn:
    """对话一轮（peer-to-peer，两方平等）。"""

    speaker: str
    text: str
    dia_id: str  # 形如 "D{session}:{turn}"，会话内唯一
    session: int
    caption: str | None = None  # VLM caption（按 dia_id 从变体移植；死链轮为 None）
    img_urls: list[str] = field(default_factory=list)


@dataclass
class LoCoMoSession:
    """一个会话（session_N）：一次 ingest 的单位。"""

    session_id: int
    datetime_raw: str  # 原文时间戳（"1:56 pm on 8 May, 2023"）
    timestamp_iso: str  # 解析后的 ISO（"2023-05-08T13:56:00"），供 IngestInput.timestamp
    turns: list[LoCoMoTurn] = field(default_factory=list)

    @property
    def chunk_id(self) -> str:
        """source_tracking 的 chunk_id（session 级溯源）。"""
        return f"session_{self.session_id}"

    @property
    def display_time(self) -> str:
        """拼接文本每行前缀的时间串（保留原文形态，喂给 LLM 抽 ③b 锚点）。"""
        return self.datetime_raw


@dataclass
class LoCoMoQA:
    """一道 QA 题。"""

    qid: str  # resume 键（sample_id + question 的 md5[:12]）
    question: str
    category: int  # 1-5
    answer: str | None = None  # cat-5 多数为 None（只有 adversarial_answer）
    adversarial_answer: str | None = None  # 仅 cat-5
    evidence: list[str] = field(default_factory=list)  # dia_id 串（V1 移植，可能空）

    @property
    def category_name(self) -> str:
        return CATEGORY_NAMES.get(self.category, f"cat-{self.category}")

    @property
    def evidence_sessions(self) -> set[int]:
        """gold session 集合（evidence dia_id 的 D{N} 前缀去重）。"""
        out: set[int] = set()
        for d in self.evidence:
            n = dia_id_to_session(d)
            if n is not None:
                out.add(n)
        return out


@dataclass
class LoCoMoDoc:
    """一个对话（sample_id）：一个独立 db、一个对话 universe。"""

    sample_id: str
    speaker_a: str
    speaker_b: str
    sessions: list[LoCoMoSession] = field(default_factory=list)
    qa_list: list[LoCoMoQA] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 纯函数（单测目标，不调 LLM）
# ---------------------------------------------------------------------------


def parse_timestamp(raw: str) -> datetime:
    """``"1:56 pm on 8 May, 2023"`` -> ``datetime``。

    手动解析（locale 无关）——Windows 中文 locale 下 ``strptime`` 的 ``%B``/``%p``
    不认英文月份 / am-pm，故用显式月份表。实测 288 会话 0 失败。
    """
    m = _TS_RE.match(raw.strip())
    if not m:
        raise ValueError(f"无法解析时间戳：{raw!r}")
    hh, mm, ampm, day, mon, year = m.groups()
    hour = int(hh) % 12
    if ampm.lower() == "pm":
        hour += 12
    month = _MONTHS.get(mon.lower())
    if month is None:
        raise ValueError(f"未知月份：{mon!r}")
    return datetime(int(year), month, int(day), hour, int(mm))


def dia_id_to_session(dia_id: str) -> int | None:
    """``"D1:3"`` -> ``1``；不合规返 ``None``。"""
    m = _DIA_RE.match(dia_id)
    return int(m.group(1)) if m else None


def strip_audit_tags(text: Any) -> str:
    """去掉答案尾部的 ``[LOCOMO-AUDIT]`` / ``[LOCOMO-ISSUES]`` 标注。

    容忍非字符串（实测 V2 个别 answer 是裸数字如 ``2023``）——强转 ``str`` 后再剥离。
    """
    if text is None or text == "":
        return ""
    return _AUDIT_RE.sub("", str(text)).strip()


def apply_rename(text: str, rename_map: dict[str, str]) -> str:
    """按换名映射做**词边界、大小写不敏感**替换。

    单遍正则替换（长名优先，防前缀碰撞如 "Jon"/"Jonathan"），避免顺序替换的连环
    误伤。``rename_map`` 由两版 ``speaker_a/b`` 机械建立（每对话 2 项），**不经 LLM**。
    """
    if not rename_map or not text:
        return text
    lut = {k.lower(): v for k, v in rename_map.items()}
    # 长名优先：先替 "Jessica" 再替 "Jess" 之类，防短名吃掉长名前缀。
    names = sorted(lut, key=len, reverse=True)
    pat = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b", re.IGNORECASE)
    return pat.sub(lambda m: lut[m.group(0).lower()], text)


def make_qid(sample_id: str, question: str, index: int = 0) -> str:
    """稳定题 id——resume 键。

    含 conv 内序号 ``index``：实测 V2 base 有 12 组重复 (sample_id, question)
    （同对话里同问题出现两次，可能不同类别/答案）。不含序号会让重复题共享 qid，
    导致 resume 误跳过、指标聚合错算。故 qid 对**每个 qa 对象**唯一。
    """
    return hashlib.md5(f"{sample_id}|{index}|{question}".encode("utf-8")).hexdigest()[:12]


def build_rename_map(v1_conv: dict, v2_conv: dict) -> dict[str, str]:
    """由两版 ``conversation.speaker_a/speaker_b`` 机械建立 V1->V2 换名映射。

    每对话 2 项（speaker_a/b），换名从不出现在同对话内（V2 全部换名）。跨对话
    "John"/"Jack" 等碰撞由 sample_id 键控消除——**绝不做全局替换**。
    """
    mp: dict[str, str] = {}
    vc1, vc2 = v1_conv.get("conversation", {}), v2_conv.get("conversation", {})
    for v1, v2 in ((vc1.get("speaker_a"), vc2.get("speaker_a")),
                   (vc1.get("speaker_b"), vc2.get("speaker_b"))):
        if v1 and v2 and v1 != v2:
            mp[v1] = v2
    return mp


def filter_by_category(
    qas: list[LoCoMoQA], categories: int | Iterable[int]
) -> list[LoCoMoQA]:
    """按类别过滤 QA（``categories`` 为单个 int 或其可迭代集合）。"""
    cats: set[int] = {categories} if isinstance(categories, int) else set(categories)
    return [q for q in qas if q.category in cats]


# ---------------------------------------------------------------------------
# 三源合成装载器
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"数据文件不存在：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_sessions(conv: dict) -> list[tuple[int, str, list[dict]]]:
    """从 conversation dict 抽 ``(session_id, datetime_raw, turns)``。

    conversation 按 ``session_N_date_time`` / ``session_N`` 交错存放。**只取同时有
    date_time 与 turn-list 的会话**——conv-26 有 16 个 date_time-only 残桩
    （session_20..35）须丢弃。
    """
    ts: dict[int, str] = {}
    turns: dict[int, list[dict]] = {}
    conv_body = conv.get("conversation", {})
    for key in conv_body:
        m_ts = _SESSION_TS_KEY_RE.match(key)
        if m_ts:
            ts[int(m_ts.group(1))] = conv_body[key]
            continue
        m_t = _SESSION_KEY_RE.match(key)
        if m_t:
            turns[int(m_t.group(1))] = conv_body[key]
    return [(n, ts.get(n, ""), turns[n]) for n in sorted(turns)]


def _build_caption_lookup(
    cap_by: dict[str, dict], cap_field: str, base_by: dict[str, dict]
) -> tuple[dict[tuple[str, str], str], int]:
    """按 ``(sample_id, dia_id)`` 建立 caption 查找表，并校验变体 conversation 与 base 逐轮一致。

    返回 ``(lookup, 非空 caption 计数)``。变体 turn text 与 base 不一致即报错（D1 一致性约束）。
    """
    lookup: dict[tuple[str, str], str] = {}
    count = 0
    for sid, cap_conv in cap_by.items():
        cap_turns: dict[str, dict] = {}
        for _n, _raw, tl in _iter_sessions(cap_conv):
            for t in tl:
                cap_turns[t.get("dia_id", "")] = t
        # 一致性校验：caption 变体 conversation 逐轮 text == base（防版本漂移静默移植错位）。
        base_conv = base_by.get(sid)
        if base_conv is not None:
            for _n, _raw, tl in _iter_sessions(base_conv):
                for t in tl:
                    dia = t.get("dia_id", "")
                    ct = cap_turns.get(dia)
                    if ct is not None and ct.get("text", "") != t.get("text", ""):
                        raise ValueError(
                            f"caption 变体 conversation 与 base 逐轮不一致："
                            f"sample_id={sid} dia_id={dia}（变体版本漂移）"
                        )
        for dia, t in cap_turns.items():
            cap = (t.get(cap_field) or "").strip()
            if cap:
                lookup[(sid, dia)] = cap
                count += 1
    return lookup, count


def _migrate_evidence(
    v1_by: dict[str, dict], base_by: dict[str, dict]
) -> tuple[dict[str, list[str]], int, int, int]:
    """把 V1 ``evidence`` 按换名映射移植到 V2 题（诊断指标）。

    返回 ``(qid -> evidence 列表, V2 挂上 evidence 的题数, 命中数, V1 evidence-bearing 总数)``。
    移植方法：V1 问题经换名映射（词边界、大小写不敏感）替换后，与 V2 问题做**大小写不敏感
    精确匹配**；命中者把 V1 ``evidence`` 挂到**所有**同文本 V2 题（含 12 组重复题）。
    """
    evidence_by_q: dict[str, list[str]] = {}
    touched: set[str] = set()
    hit = 0
    total = 0
    for sid, v1_conv in v1_by.items():
        base_conv = base_by.get(sid)
        if base_conv is None:
            continue
        rename = build_rename_map(v1_conv, base_conv)
        # V2 问题大小写不敏感索引：lower(question) -> [qid...]（重复题全收，含序号唯一 qid）。
        v2_index: dict[str, list[str]] = {}
        for idx, q in enumerate(base_conv.get("qa", [])):
            v2_index.setdefault(q["question"].strip().lower(), []).append(
                make_qid(sid, q["question"], idx)
            )
        for q in v1_conv.get("qa", []):
            ev = q.get("evidence") or []
            if not ev:
                continue
            total += 1
            renamed = apply_rename(q["question"].strip(), rename).lower()
            for qid in v2_index.get(renamed, []):
                hit += 1
                evidence_by_q.setdefault(qid, []).extend(ev)
                touched.add(qid)
    return evidence_by_q, len(touched), hit, total


class LoCoMoDataLoader:
    """LoCoMo 三源合成装载器（D1）。

    主体 = V2 base；caption 取所选变体（默认 moondream）按 ``dia_id`` 移植；evidence
    从 V1_source 按换名映射移植。``validate=True`` 时校验类别分布、caption 移植数、
    evidence 命中率（数据版本漂移即报错）。预处理结果按源文件 mtime 缓存到
    ``data/preprocessed/``。
    """

    def __init__(
        self,
        base_path: str | Path = DEFAULT_BASE,
        *,
        caption_variant: str = "moondream",
        caption_path: str | Path | None = None,
        v1_source_path: str | Path = DEFAULT_V1_SOURCE,
        cache_dir: str | Path | None = PREPROCESSED_DIR,
        validate: bool = True,
    ) -> None:
        if caption_variant not in CAPTION_VARIANT_FIELD:
            raise ValueError(
                f"未知 caption 变体 {caption_variant!r}（可选 {list(CAPTION_VARIANT_FIELD)}）"
            )
        self.base_path = Path(base_path)
        self.caption_variant = caption_variant
        self.caption_path = (
            Path(caption_path)
            if caption_path is not None
            else DEFAULT_CAPTION_DIR / CAPTION_VARIANT_FILE[caption_variant]
        )
        self.v1_source_path = Path(v1_source_path)
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.validate = validate

    # -- 公开 API --

    def load(self) -> list[LoCoMoDoc]:
        """装载并合成 10 个对话（命中缓存则直接返回）。"""
        cache_path = self._cache_path()
        if cache_path is not None and cache_path.exists() and not self._cache_stale(cache_path):
            try:
                with cache_path.open("rb") as fh:
                    docs: list[LoCoMoDoc] = pickle.load(fh)
                logger.info("LoCoMo 命中缓存：%s（%d 对话）", cache_path, len(docs))
                return docs
            except Exception:
                logger.warning("缓存反序列化失败，重建：%s", cache_path, exc_info=True)

        docs = self._build()
        if self.cache_dir is not None:
            self._write_cache(docs)
        return docs

    def load_doc(self, sample_id: str) -> LoCoMoDoc:
        """装载单个对话。"""
        for d in self.load():
            if d.sample_id == sample_id:
                return d
        raise KeyError(f"未找到对话：{sample_id}")

    # -- 合成 --

    def _build(self) -> list[LoCoMoDoc]:
        base = _load_json(self.base_path)
        caption = _load_json(self.caption_path)
        v1 = _load_json(self.v1_source_path)
        cap_field = CAPTION_VARIANT_FIELD[self.caption_variant]

        base_by = {c["sample_id"]: c for c in base}
        cap_by = {c["sample_id"]: c for c in caption}
        v1_by = {c["sample_id"]: c for c in v1}

        cap_lookup, cap_count = _build_caption_lookup(cap_by, cap_field, base_by)
        evidence_by_q, n_ev, ev_hit, ev_total = _migrate_evidence(v1_by, base_by)

        docs: list[LoCoMoDoc] = []
        for c in base:
            sid = c["sample_id"]
            conv = c.get("conversation", {})
            doc = LoCoMoDoc(
                sample_id=sid,
                speaker_a=conv.get("speaker_a", ""),
                speaker_b=conv.get("speaker_b", ""),
            )
            for n, raw, turns in _iter_sessions(c):
                ts_iso = parse_timestamp(raw).isoformat() if raw else ""
                sess = LoCoMoSession(session_id=n, datetime_raw=raw, timestamp_iso=ts_iso)
                for t in turns:
                    dia = t.get("dia_id", "")
                    sess.turns.append(LoCoMoTurn(
                        speaker=t.get("speaker", ""),
                        text=t.get("text", ""),
                        dia_id=dia,
                        session=n,
                        caption=cap_lookup.get((sid, dia)),
                        img_urls=list(t.get("img_url") or []),
                    ))
                doc.sessions.append(sess)
            for idx, q in enumerate(c.get("qa", [])):
                qid = make_qid(sid, q["question"], idx)
                doc.qa_list.append(LoCoMoQA(
                    qid=qid,
                    question=q["question"],
                    category=int(q["category"]),
                    answer=strip_audit_tags(q.get("answer")) or None,
                    adversarial_answer=q.get("adversarial_answer"),
                    evidence=list(evidence_by_q.get(qid, [])),
                ))
            docs.append(doc)

        if self.validate:
            self._validate(docs, cap_count, n_ev, ev_hit, ev_total)
        return docs

    # -- 校验 --

    def _validate(
        self,
        docs: list[LoCoMoDoc],
        cap_count: int,
        n_v2_with_evidence: int,
        ev_hit: int,
        ev_total: int,
    ) -> None:
        # 类别分布（硬校验，漂移即报错）。
        dist = Counter()
        for d in docs:
            for q in d.qa_list:
                dist[q.category] += 1
        actual = dict(sorted(dist.items()))
        if actual != EXPECTED_CATEGORY_COUNTS:
            raise ValueError(
                f"V2 类别分布漂移：实际 {actual} ≠ 期望 {EXPECTED_CATEGORY_COUNTS}"
                f"（总 {sum(dist.values())}，预期 1922）——数据版本不符"
            )

        total_qa = sum(len(d.qa_list) for d in docs)
        ev_rate = n_v2_with_evidence / total_qa if total_qa else 0.0
        if ev_rate < MIN_EVIDENCE_HIT_RATE:
            raise ValueError(
                f"evidence 移植命中率 {ev_rate:.1%}（{n_v2_with_evidence}/{total_qa}）"
                f" < {MIN_EVIDENCE_HIT_RATE:.0%}——换名映射可能失效"
            )
        logger.info(
            "evidence 移植命中率 %.1f%%（V2 挂上 %d/%d；V1 命中 %d/%d）",
            100 * ev_rate, n_v2_with_evidence, total_qa, ev_hit, ev_total,
        )

        # caption 移植数：moondream 硬校验（spec scenario），其他变体仅警告。
        if self.caption_variant == "moondream" and cap_count != EXPECTED_CAPTION_COUNT:
            raise ValueError(
                f"moondream caption 移植数 {cap_count} ≠ 期望 {EXPECTED_CAPTION_COUNT}"
                f"（910 带图轮 - 76 死链）——caption 变体版本漂移"
            )
        if cap_count != EXPECTED_CAPTION_COUNT:
            logger.warning(
                "%s caption 移植数 %d（moondream 基准 %d）",
                self.caption_variant, cap_count, EXPECTED_CAPTION_COUNT,
            )

    # -- 缓存 --

    def _cache_path(self) -> Path | None:
        if self.cache_dir is None:
            return None
        vid = hashlib.md5(
            f"{self.base_path}|{self.caption_path}|{self.v1_source_path}|{self.caption_variant}"
            .encode("utf-8")
        ).hexdigest()[:8]
        return self.cache_dir / f"locomo_{self.caption_variant}_{vid}.pkl"

    def _cache_stale(self, cache_path: Path) -> bool:
        for p in (self.base_path, self.caption_path, self.v1_source_path):
            if p.exists() and cache_path.stat().st_mtime < p.stat().st_mtime:
                return True
        return False

    def _write_cache(self, docs: list[LoCoMoDoc]) -> None:
        cache_path = self._cache_path()
        if cache_path is None:
            return
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with cache_path.open("wb") as fh:
                pickle.dump(docs, fh)
        except Exception:
            logger.warning("缓存写入失败：%s", cache_path, exc_info=True)


def load(
    base_path: str | Path = DEFAULT_BASE,
    *,
    caption_variant: str = "moondream",
    validate: bool = True,
) -> list[LoCoMoDoc]:
    """便捷装载：``LoCoMoDataLoader(...).load()``。"""
    return LoCoMoDataLoader(
        base_path, caption_variant=caption_variant, validate=validate
    ).load()
