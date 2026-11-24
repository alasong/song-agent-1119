"""W8：父预算按 30/70 切给依赖侧与执行侧；份额不许超过父池剩余。"""
import unittest

from sa2 import config
from sa2.core.budget import Budget


class BudgetSplitTest(unittest.TestCase):
    def test_split_30_70(self):
        dep, work = Budget(10000).split(0.3)
        self.assertEqual(dep.tokens, 3000)
        self.assertEqual(work.tokens, 7000)

    def test_default_ratio_comes_from_thresholds(self):
        dep, work = Budget(10000).split()
        ratio = config.get("dep_budget_ratio")
        self.assertEqual(dep.tokens, int(10000 * ratio))
        self.assertEqual(work.tokens, int(10000 * (1 - ratio)))

    def test_ratio_is_clamped(self):
        dep, work = Budget(10000).split(2.0)
        self.assertEqual(dep.tokens, 10000)
        self.assertEqual(work.tokens, 0)

    def test_share_cannot_exceed_remaining(self):
        parent = Budget(100)
        parent.note("x" * 400)          # ≈100 tokens，已花光
        dep, work = parent.split(0.3)
        self.assertEqual(dep.tokens, 0)
        self.assertEqual(work.tokens, 0)

    def test_children_point_back_to_parent(self):
        parent = Budget(1000)
        dep, work = parent.split(0.3)
        self.assertIs(dep.parent, parent)
        self.assertIs(work.parent, parent)


if __name__ == "__main__":
    unittest.main()