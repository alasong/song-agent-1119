"""D5：验收锚在「能力最好做到过什么」，不锚「最后一次恰好是多少」。

三类会被误读的情形必须判对：
1. 实验性运行（purpose=experiment）不能把门翻绿——否则随便跑个小实验就能刷分；
2. 最后一次是实验或弱运行，不能抹掉更早达标过的能力；
3. G2 要按目标数算（文档写「连续 2 个新目标」），不是按报告数算。
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bench_mod", ROOT / "scripts" / "bench.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)

GOOD = {
    "goal": "目标甲", "distinct_roles": 6, "chain_ok": True, "handoffs": 13,
    "worker_mode": "llm", "stages": 2, "has_verifier": True,
    "verdicts": 2, "reworks": 2,
}


def good(**kw):
    return {**GOOD, **kw}


class AcceptanceFilterTest(unittest.TestCase):
    def test_experiment_is_excluded(self):
        records = [good(), good(purpose="experiment", stages=1, handoffs=1)]
        kept = bench.drop_experiments(records)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["goal"], "目标甲")

    def test_missing_purpose_counts_as_acceptance(self):
        kept = bench.drop_experiments([good()])
        self.assertEqual(len(kept), 1, "老报告没有 purpose 字段，不能因此被丢掉")

    def test_all_experiment_means_nothing_proven(self):
        records = [good(purpose="experiment")]
        self.assertEqual(bench.drop_experiments(records), [])
        self.assertEqual(bench.g2_goals(bench.drop_experiments(records)), {},
                         "全是实验运行 = 一条能力都没证明")


class G2CapabilityTest(unittest.TestCase):
    def test_latest_weak_run_does_not_erase_capability(self):
        """先强后弱：能力证明过就是证明过，读窗口内最好的一次。"""
        records = [good(handoffs=13), good(handoffs=4, verdicts=1, reworks=1)]
        goals = bench.g2_goals(records)
        self.assertIn("目标甲", goals)
        self.assertEqual(goals["目标甲"]["handoffs"], 13, "应取更强的那次")

    def test_two_distinct_goals_required(self):
        one = bench.g2_goals([good(goal="甲")])
        two = bench.g2_goals([good(goal="甲"), good(goal="乙")])
        self.assertEqual(len(one), 1)
        self.assertFalse(bench.g2_passed(one), "只有 1 个目标不达标（文档要求 2 个）")
        self.assertTrue(bench.g2_passed(two))

    def test_same_goal_twice_is_still_one_goal(self):
        goals = bench.g2_goals([good(goal="甲"), good(goal="甲"), good(goal="甲")])
        self.assertEqual(len(goals), 1)
        self.assertFalse(bench.g2_passed(goals), "同一目标跑三次，证明的是稳定，不是覆盖新目标")

    def test_run_without_goal_does_not_count(self):
        goals = bench.g2_goals([good(goal=""), good(goal=None), good(goal="甲")])
        self.assertEqual(list(goals), ["甲"])

    def test_structural_failure_is_not_capability(self):
        weak = good(goal="乙", stages=1)
        self.assertEqual(bench.g2_goals([weak]), {})


class G5SkeletonTest(unittest.TestCase):
    def _report(self, *heading_sets):
        return {"runs": [{"fingerprint": {"headings": list(h)}} for h in heading_sets]}

    def test_same_skeleton_passes(self):
        h = ["## 一、结论", "## 二、论证"]
        self.assertTrue(bench.g5_skeleton_ok(self._report(h, h, h)))

    def test_different_skeleton_fails(self):
        a = ["## 一、结论", "## 二、论证"]
        b = ["## 一、背景", "## 二、做法"]
        self.assertFalse(bench.g5_skeleton_ok(self._report(a, b, a)),
                         "章节骨架变了就是漂移，重合率再高也不算")

    def test_missing_fingerprint_is_not_silently_ok(self):
        self.assertFalse(bench.g5_skeleton_ok({"runs": [{"fingerprint": {}}]}))


if __name__ == "__main__":
    unittest.main()