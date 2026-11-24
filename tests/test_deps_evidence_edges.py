"""两处小边界：依赖缺名字要进问题列表、漏报归因在「没问题」时必须是空；
证据的打戳时间不是 ISO 时，台账要拒。

主路径分别在 test_deps / test_sa2_evidence；这里补的是「没人跑过的那两行」。
"""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from sa2.core import deps
from sa2.core import evidence


class DepsEdgeTest(unittest.TestCase):
    def test_unnamed_dependency_is_reported(self):
        item = deps.Assertion("", "tool", "能取回至少 2 条记录", "cmd:true", "换源")
        problems = deps.check(deps.DepNote("抓取", (item,)))
        self.assertIn("依赖缺名字", problems)

    def test_missed_without_any_problem_is_empty(self):
        item = deps.Assertion("抓取工具", "tool", "能取回至少 2 条记录",
                              "cmd:true", "换源", supports=("交付·引用",))
        self.assertEqual(deps.missed(deps.DepNote("抓取", (item,)), []), [],
                         "没有失败判据就没有漏报")


class EvidenceTimestampTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "content"
        self.book = evidence.EvidenceBook(Path(self.tmp.name) / "evidence.jsonl")

    def test_non_iso_fetched_at_is_refused_by_the_book(self):
        ev = evidence.stamp("https://example.org/x", "取回内容", "leader", "S1", self.root)
        with self.assertRaisesRegex(evidence.EvidenceError, "不是 ISO 时间"):
            self.book.add(replace(ev, fetched_at="昨天"))
        self.assertEqual(self.book.all(), [], "被拒的证据不许留下半条记录")


if __name__ == "__main__":
    unittest.main()