"""M4 的验收测试：这份由人先写，SA 只能改 scripts/w0_formalize_probe.py 来让它变绿。

要求（W0 真实需要的）：
- 任务清单从 10 条扩到 20 条以上，编号唯一、每条任务描述够具体；
- 提供 pick_tasks(n)，能取前 n 条（探针要能跑子集）；
- 原有的 probe() 入口不能被改丢。
"""
from __future__ import annotations

import unittest

from scripts import w0_formalize_probe as probe


class W0TasksTest(unittest.TestCase):
    def test_at_least_20_tasks(self):
        self.assertGreaterEqual(len(probe.TASKS), 20)

    def test_ids_are_unique(self):
        ids = [task[0] for task in probe.TASKS]
        self.assertEqual(len(ids), len(set(ids)), f"编号重复：{ids}")

    def test_texts_are_specific(self):
        for task_id, text in probe.TASKS:
            self.assertGreaterEqual(len(text), 10, f"{task_id} 的任务描述太短")

    def test_pick_tasks_limits(self):
        self.assertEqual(probe.pick_tasks(3), probe.TASKS[:3])
        self.assertEqual(probe.pick_tasks(0), [])

    def test_probe_entry_survives(self):
        self.assertTrue(callable(probe.probe))


if __name__ == "__main__":
    unittest.main()