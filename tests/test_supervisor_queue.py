"""派活队列的坏数据与生命周期：坏行带行号报错、缺字段报错、结不存在的单要 KeyError。

队列是「进程死了记录还在」的唯一凭据，它静默吞一行就等于丢一次派活。
`test_sa2_liveness` 盖的是正常 put/all 路径，这里补坏数据面。
"""
import json
import tempfile
import unittest
from pathlib import Path

from sa2.loop.supervisor import DispatchQueue


def row(dispatch_id="d1", **kw) -> dict:
    base = {"id": dispatch_id, "role_id": "执行", "stage": "起草", "duty": "写",
            "criteria": "齐全", "attempt": 1, "input_ref": ""}
    base.update(kw)
    return base


class DispatchQueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "dispatches.jsonl"
        self.queue = DispatchQueue(self.path)

    def write_lines(self, *lines: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_blank_lines_are_skipped(self):
        self.write_lines(json.dumps(row("d1"), ensure_ascii=False), "",
                         json.dumps(row("d2"), ensure_ascii=False))
        self.assertEqual(sorted(d.id for d in self.queue.all()), ["d1", "d2"])

    def test_corrupt_line_names_its_number_and_path(self):
        self.write_lines(json.dumps(row("d1"), ensure_ascii=False), "{这一行坏了")
        with self.assertRaises(ValueError) as caught:
            self.queue.all()
        message = str(caught.exception)
        self.assertIn("第 2 行", message)
        self.assertIn(str(self.path), message)

    def test_row_missing_fields_is_refused(self):
        broken = row("d1")
        broken.pop("role_id")
        self.write_lines(json.dumps(broken, ensure_ascii=False))
        with self.assertRaisesRegex(ValueError, "缺字段"):
            self.queue.all()

    def test_finishing_unknown_dispatch_raises(self):
        with self.assertRaises(KeyError):
            self.queue.finish("d-none", "done")

    def test_latest_row_wins(self):
        self.write_lines(json.dumps(row("d1", state="leased"), ensure_ascii=False),
                         json.dumps(row("d1", state="done"), ensure_ascii=False))
        self.assertEqual(self.queue.all()[0].state, "done")


if __name__ == "__main__":
    unittest.main()