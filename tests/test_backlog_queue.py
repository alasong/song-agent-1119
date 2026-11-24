"""目标队列的写入门：来源/状态是闭集，坏行跳过，标记不存在的目标要拒。

`test_sa2_daemon` 盖的是领取规则（自助目标没批准不许领）；这里补写入面——
闭集校验与「状态事件只追加」的容错，红线在 L3 的形态靠这两处兜底。
"""
import json
import tempfile
import unittest
from pathlib import Path

from sa2.autonomy.backlog import STATUSES, Goal, Backlog


def goal(text="写一份报告", source="leader", status="pending", **kw) -> Goal:
    return Goal(text=text, dims=("correctness",), criteria=("章节",), budget_tokens=1000,
                source=source, status=status, **kw)


class BacklogWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "backlog.jsonl"
        self.queue = Backlog(self.path)

    def test_unknown_source_is_refused(self):
        with self.assertRaisesRegex(ValueError, "来源只能是"):
            self.queue.add(goal(source="外来的"))

    def test_unknown_status_is_refused(self):
        with self.assertRaisesRegex(ValueError, "状态只能是"):
            self.queue.add(goal(status="做梦"))

    def test_blank_and_corrupt_lines_are_skipped(self):
        self.queue.add(goal())
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write("\n")
            fh.write("{坏行\n")
        self.assertEqual(len(self.queue.all()), 1)

    def test_mark_unknown_status_is_refused(self):
        item = self.queue.add(goal())
        with self.assertRaisesRegex(ValueError, "状态只能是"):
            self.queue.mark(item, "做梦")

    def test_mark_unknown_goal_is_refused(self):
        self.queue.add(goal())
        with self.assertRaisesRegex(ValueError, "队列里没有这个目标"):
            self.queue.mark(goal(text="没入过队的目标"), "done")

    def test_mark_appends_and_flips_status(self):
        item = self.queue.add(goal())
        self.queue.mark(item, "done")
        self.assertEqual({g.text: g.status for g in self.queue.all()}, {"写一份报告": "done"})
        self.assertIn("done", STATUSES)


if __name__ == "__main__":
    unittest.main()