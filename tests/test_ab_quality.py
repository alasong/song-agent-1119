"""A/B 比较：质量分进去之后，判定要跟着变，而不是只看成本。"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ab_mod", ROOT / "scripts" / "ab_test.py")
ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ab)

BASE = {"passed": True, "rounds": 1, "chars": 3000, "calls": 5,
        "prompt_tokens": 4000, "completion_tokens": 3000}


class CompareTest(unittest.TestCase):
    def test_without_quality_cost_only(self):
        a = {**BASE, "calls": 3, "prompt_tokens": 1000}
        b = {**BASE, "calls": 5}
        verdict = ab.compare(a, b)
        self.assertIn("A", verdict["better"])

    def test_quality_flips_the_verdict_to_undecided(self):
        """B 更贵但分更高：加上质量分后不再是 A 独占优势。"""
        a = {**BASE, "calls": 3, "prompt_tokens": 1000, "quality_total": 7}
        b = {**BASE, "calls": 5, "quality_total": 12}
        verdict = ab.compare(a, b)
        self.assertIn("quality_total", verdict["better"]["B"])
        self.assertEqual(verdict["verdict"], "互有胜负，无 Pareto 占优")

    def test_quality_tie_does_not_change_anything(self):
        a = {**BASE, "calls": 3, "prompt_tokens": 1000, "quality_total": 10}
        b = {**BASE, "calls": 5, "quality_total": 10}
        self.assertIn("quality_total", ab.compare(a, b)["better"]["tie"])

    def test_quality_only_on_one_side_is_ignored(self):
        a = {**BASE, "calls": 3, "prompt_tokens": 1000, "quality_total": 9}
        b = {**BASE, "calls": 5}
        self.assertNotIn("quality_total", ab.compare(a, b)["better"].get("A", []))


class JudgeBlindPathTest(unittest.TestCase):
    def test_judge_pair_maps_scores_back(self):
        """judge_pair 用 make_llm 打真接口，这里只验映射函数本身没把 A/B 搞反。"""
        import xm.quality as q
        payload = {"scores": [{"doc": 1, "dims": {d: 0 for d in q.DIMS}},
                              {"doc": 2, "dims": {d: 3 for d in q.DIMS}}]}
        res = q.judge(["甲", "乙"], lambda m: __import__("json").dumps(payload), seed=0)
        by_index = {r["index"]: r for r in res["scores"]}
        # 文档 2 得分高，它对应原始下标 order[1]
        self.assertEqual(res["winner"], q.order_for(2, 0)[1])
        self.assertEqual(by_index[q.order_for(2, 0)[1]]["total"], 15)


if __name__ == "__main__":
    unittest.main()