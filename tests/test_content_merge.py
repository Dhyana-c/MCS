"""merge_content helper 测试：四象限 + 降级。

落实 unified-graph-schema「图质量最终收敛」content 合并守则：
子串零成本 / 非子串按 LLM 可用性分流（write 传 LLM、query+dedup 不传）。
"""

from __future__ import annotations

import logging

from mcs.core.content_merge import merge_content, substring_relation


class TestMergeContent:
    def test_incoming_empty_keeps_target(self):
        """incoming 空 → 保留 target。"""
        assert merge_content("abc", "") == "abc"
        assert merge_content("abc", "   ") == "abc"

    def test_target_empty_uses_incoming(self):
        """target 空、incoming 非空 → 用 incoming。"""
        assert merge_content("", "xyz") == "xyz"
        assert merge_content("   ", "xyz") == "xyz"

    def test_incoming_is_substring_skips(self):
        """incoming 已含于 target → 跳过（零成本，不调 LLM）。"""
        assert merge_content("abcdef", "bcd") == "abcdef"
        assert merge_content("苹果公司科技", "苹果公司") == "苹果公司科技"

    def test_target_is_substring_replaces(self):
        """target 是 incoming 子串 → 替换为 incoming（更全）。"""
        assert merge_content("bcd", "abcdef") == "abcdef"
        assert merge_content("X", "XYZ") == "XYZ"

    def test_non_substring_no_llm_returns_target(self):
        """非子串 + 无 LLM（query read-repair / dedup）→ 不碰，返回 target。"""
        assert merge_content("苹果公司", "苹果水果", merge_llm=None) == "苹果公司"
        assert merge_content("abc", "xyz") == "abc"

    def test_non_substring_with_llm_merges(self):
        """非子串 + LLM（write path）→ 调 LLM 语义合并。"""
        calls: list[tuple[str, str]] = []

        def llm(t: str, i: str) -> str:
            calls.append((t, i))
            return "合并定义"

        assert merge_content("苹果公司", "苹果水果", merge_llm=llm) == "合并定义"
        assert calls == [("苹果公司", "苹果水果")]

    def test_llm_failure_degrades_to_target(self, caplog):
        """LLM 异常 → 降级返回 target + warning（不抛）。"""

        def llm(t: str, i: str) -> str:
            raise RuntimeError("LLM down")

        with caplog.at_level(logging.WARNING):
            assert merge_content("苹果公司", "苹果水果", merge_llm=llm) == "苹果公司"
        assert any("LLM 合并失败" in r.message for r in caplog.records)

    def test_llm_empty_degrades_to_target(self, caplog):
        """LLM 返回空 → 降级返回 target + warning。"""

        def llm(t: str, i: str) -> str:
            return "   "

        with caplog.at_level(logging.WARNING):
            assert merge_content("苹果公司", "苹果水果", merge_llm=llm) == "苹果公司"
        assert any("LLM 返回空" in r.message for r in caplog.records)

    def test_llm_result_stripped(self):
        """LLM 返回带前后空白 → strip。"""

        def llm(t: str, i: str) -> str:
            return "  合并定义  "

        assert merge_content("a内容", "b内容", merge_llm=llm) == "合并定义"


def test_substring_relation_classifies_contains():
    """substring_relation：子串包含 / 相等 / 非子串 / 一方空（merge_content 与 dedup 共口径）。"""
    # incoming ⊆ target
    assert substring_relation("苹果公司科技", "苹果公司") == "target"
    assert substring_relation("abcdef", "bcd") == "target"
    # target ⊆ incoming
    assert substring_relation("苹果公司", "苹果公司科技") == "incoming"
    assert substring_relation("bcd", "abcdef") == "incoming"
    # 相等 → incoming ⊆ target
    assert substring_relation("苹果", "苹果") == "target"
    # 非子串
    assert substring_relation("苹果公司", "苹果水果") is None
    assert substring_relation("abc", "xyz") is None
    # 一方空 → 视为对方子串（与 merge_content 空方逻辑一致）
    assert substring_relation("abc", "") == "target"
    assert substring_relation("", "xyz") == "incoming"
    assert substring_relation("abc", "   ") == "target"
