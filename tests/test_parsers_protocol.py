"""取回文本的解析协议：同协议换站点只改数据，坏数据当场抛、缺字段不整批失败。

`test_sa2_knowledge` 盖了两个具体源的成功路径；这里打通用 JSON API 的字段映射、
坏 JSON、条目缺标题，以及 `_dig` / `_flat` 的边界——它们是「换个站点只改一行数据」的承载点。
"""
import json
import unittest

from sa2 import parsers


class DigTest(unittest.TestCase):
    def test_missing_segments_return_empty_string(self):
        self.assertEqual(parsers._dig({"a": None}, "a.b"), "", "中途遇到 None")
        self.assertEqual(parsers._dig({"a": [1]}, "a.5"), "", "列表下标越界")
        self.assertEqual(parsers._dig({"a": [1]}, "a.x"), "", "列表下标不是数字")
        self.assertEqual(parsers._dig("字符串", "a"), "", "标量上继续下钻")

    def test_flat_joins_list_and_collapses_whitespace(self):
        self.assertEqual(parsers._flat(["标题甲", "副标题"]), "标题甲 副标题")
        self.assertEqual(parsers._flat("  多  空格  "), "多 空格")

    def test_flat_truncates(self):
        self.assertEqual(len(parsers._flat("字" * 5000)), 600)


class JsonApiTest(unittest.TestCase):
    SPEC = {"fields": {"items": "message.items", "id": "DOI", "title": "title.0",
                       "published": "created.date-parts.0.0", "url": "URL"}}

    def payload(self, items):
        return json.dumps({"message": {"items": items}}, ensure_ascii=False)

    def test_maps_fields_through_dotted_paths(self):
        items = [{"DOI": "10.1/x", "title": ["标题甲"],
                  "created": {"date-parts": [[2026, 11, 1]]}, "URL": "https://e/x"}]
        entries = parsers.parse("json_api", self.payload(items), self.SPEC)
        self.assertEqual(entries[0]["id"], "10.1/x")
        self.assertEqual(entries[0]["title"], "标题甲")
        self.assertEqual(entries[0]["published"], "2026")
        self.assertEqual(entries[0]["url"], "https://e/x")

    def test_summary_falls_back_to_title(self):
        entries = parsers.parse("json_api", self.payload([{"DOI": "d", "title": ["甲"]}]),
                                self.SPEC)
        self.assertEqual(entries[0]["summary"], "甲")

    def test_items_without_title_are_skipped_then_reported(self):
        with self.assertRaisesRegex(parsers.ParseError, "没有可用条目"):
            parsers.parse("json_api", self.payload([{"DOI": "d", "title": [""]}]), self.SPEC)

    def test_items_not_a_list_is_not_silently_empty(self):
        with self.assertRaisesRegex(parsers.ParseError, "没有可用条目"):
            parsers.parse("json_api", json.dumps({"message": {"items": "一行字"}}), self.SPEC)

    def test_bad_json_is_refused(self):
        with self.assertRaisesRegex(parsers.ParseError, "不是 JSON"):
            parsers.parse("json_api", "这不是 JSON", self.SPEC)

    def test_missing_field_mapping_is_refused(self):
        with self.assertRaisesRegex(parsers.ParseError, "缺字段映射"):
            parsers.parse("json_api", "{}", {})


class HnTest(unittest.TestCase):
    def test_hit_without_title_is_skipped_not_fatal(self):
        text = json.dumps({"hits": [{"objectID": 1}, {"objectID": 2, "title": "甲"}]},
                          ensure_ascii=False)
        entries = parsers.parse("hn_json", text)
        self.assertEqual([e["title"] for e in entries], ["甲"])

    def test_bad_json_is_refused(self):
        with self.assertRaisesRegex(parsers.ParseError, "不是 JSON"):
            parsers.parse("hn_json", "{坏")

    def test_no_url_points_back_to_discussion(self):
        text = json.dumps({"hits": [{"objectID": 7, "title": "甲"}]}, ensure_ascii=False)
        self.assertIn("item?id=7", parsers.parse("hn_json", text)[0]["url"])


if __name__ == "__main__":
    unittest.main()