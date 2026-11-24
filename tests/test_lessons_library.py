"""经验库的容错边界：空正文拒收、坏行跳过而不是整库挂掉、查询条件必须登记。

`test_sa2_lesson_flow` / `test_sa2_knowledge` 盖了增删匹配的主路径；这里补
「库是重建得出来的」那几条：写坏一行不许让别人跟着陪葬，但查询写错条件要当场抛。
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sa2.memory import lessons


class LessonLibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "lessons.jsonl"

    def test_empty_body_is_refused(self):
        with self.assertRaisesRegex(lessons.LessonError, "没有正文"):
            lessons.add(self.path, "   ", {"failure_kind": "zero_hit"})
        self.assertFalse(self.path.exists(), "被拒的经验不许落盘")

    def test_blank_and_corrupt_lines_are_skipped(self):
        good = lessons.add(self.path, "零命中时先换关键词", {"failure_kind": "zero_hit"})
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write("\n")
            fh.write("{这一行坏了\n")
        rows = lessons.all(self.path)
        self.assertEqual([r["id"] for r in rows], [good["id"]])

    def test_match_without_condition_is_empty(self):
        lesson = lessons.add(self.path, "零命中时先换关键词", {"failure_kind": "zero_hit"})
        self.assertEqual(lessons.match([lesson], {}), [])

    def test_match_with_unregistered_condition_raises(self):
        lesson = lessons.add(self.path, "零命中时先换关键词", {"failure_kind": "zero_hit"})
        with self.assertRaisesRegex(lessons.LessonError, "未登记的条件"):
            lessons.match([lesson], {"mood": "angry"})

    def test_classify_with_broken_rule_raises_instead_of_misclassifying(self):
        rules = {"failure_patterns": [{"kind": "zero_hit", "pattern": "(未闭合"}]}
        with mock.patch.object(lessons, "load", lambda name: rules if name == "classify" else {}):
            with self.assertRaisesRegex(lessons.LessonError, "正则编不过"):
                lessons.classify(["零命中"])

    def test_bump_with_empty_ids_is_a_noop(self):
        lessons.add(self.path, "零命中时先换关键词", {"failure_kind": "zero_hit"})
        before = self.path.read_text(encoding="utf-8")
        self.assertEqual(lessons.bump(self.path, []), 0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()