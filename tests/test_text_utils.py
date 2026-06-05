"""mcs.utils.text_utils 的解析辅助测试。

重点：宽容 JSON 提取——围栏、尾部多余文本、以及被 max_tokens / 小模型
截断的"裸 JSON"都应尽量救回，而不是整段丢弃。
"""

from __future__ import annotations

import json

from mcs.utils.text_utils import extract_json, strip_json_fence


class TestStripJsonFence:
    def test_no_fence(self):
        assert strip_json_fence('[{"a": 1}]') == '[{"a": 1}]'

    def test_json_fence(self):
        assert strip_json_fence('```json\n[1, 2]\n```') == '[1, 2]'

    def test_plain_fence(self):
        assert strip_json_fence('```\n{"a": 1}\n```') == '{"a": 1}'


class TestExtractJson:
    def test_bare_array(self):
        assert json.loads(extract_json('[{"a": 1}]')) == [{"a": 1}]

    def test_bare_object(self):
        assert json.loads(extract_json('{"a": 1}')) == {"a": 1}

    def test_fenced(self):
        out = extract_json('```json\n[{"a": 1}]\n```')
        assert json.loads(out) == [{"a": 1}]

    def test_trailing_prose_after_json(self):
        # JSON 后面跟解释文字 → 只取合法 JSON 部分
        out = extract_json('[{"a": 1}]\n\n以上是抽取结果。')
        assert json.loads(out) == [{"a": 1}]

    def test_leading_prose_before_json(self):
        out = extract_json('结果如下：\n[{"a": 1}]')
        assert json.loads(out) == [{"a": 1}]

    def test_truncated_array_salvages_complete_objects(self):
        # 裸数组被截断在第三个对象的字符串中途 → 应救回前两个完整对象
        raw = (
            '[{"name": "A", "content": "a"}, '
            '{"name": "B", "content": "b"}, '
            '{"name": "C", "content": "C'
        )
        out = extract_json(raw)
        data = json.loads(out)  # 不应抛 JSONDecodeError
        assert [d["name"] for d in data] == ["A", "B"]

    def test_no_json_returns_empty(self):
        assert extract_json("no json here") == ""
        assert extract_json("") == ""
