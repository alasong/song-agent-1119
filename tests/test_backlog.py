"""目标树 → 任务的解析验收。"""
import tempfile
import unittest
from pathlib import Path

from xm.backlog import Task, load, next_ready

SAMPLE = """# ROADMAP

## 7. 当前进度

| 里程碑 | 状态 | 证据 |
|---|---|---|
| A 测量仪 | 完成 | reports/a.json |
| B 骨架 | 未开始 | — |
| C 治理 | 未开始 | — |
"""

ALL_DONE = """# ROADMAP

## 7. 当前进度

| 里程碑 | 状态 | 证据 |
|---|---|---|
| A 测量仪 | 完成 | reports/a.json |
"""


def write(text: str) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    tmp.write(text)
    tmp.close()
    return Path(tmp.name)


class BacklogTest(unittest.TestCase):
    def test_load_parses_rows(self):
        tasks = load(write(SAMPLE))
        self.assertEqual([t.name for t in tasks], ["A 测量仪", "B 骨架", "C 治理"])

    def test_done_flag(self):
        tasks = load(write(SAMPLE))
        self.assertTrue(tasks[0].done)
        self.assertFalse(tasks[1].done)

    def test_next_ready_skips_done(self):
        task = next_ready(load(write(SAMPLE)))
        self.assertIsNotNone(task)
        self.assertEqual(task.name, "B 骨架")

    def test_next_ready_none_when_all_done(self):
        self.assertIsNone(next_ready(load(write(ALL_DONE))))

    def test_slug_is_ascii_safe(self):
        self.assertEqual(Task("M1 骨架+指标", "未开始", "").slug, "m1")

    def test_missing_section_raises(self):
        with self.assertRaises(ValueError):
            load(write("# 空文件"))


if __name__ == "__main__":
    unittest.main()