"""S6：对超可判。L0/L1/L2 的判定与「四件套缺一不许称更优」。"""
from __future__ import annotations

import json
import unittest

from sa2.loop.blind import blind_score
from sa2.loop.compare import dominates, pareto, verdict


class CompareTest(unittest.TestCase):
    def test_one_arm_dominates_is_l1(self):
        arms = {"single": {"passed": True, "tokens": 100, "chars": 100},
                "team": {"passed": True, "tokens": 300, "chars": 100}}
        out = verdict(arms, budget=1000, criteria_version="c1")
        self.assertEqual(out["level"], "L1")
        self.assertEqual(out["winner"], "single")

    def test_tradeoff_is_l2_not_a_claim(self):
        # 单人省 token，团队篇幅更长：各赢一维，谁都不占优
        arms = {"single": {"passed": True, "tokens": 100, "chars": 100},
                "team": {"passed": True, "tokens": 300, "chars": 200}}
        out = verdict(arms, budget=1000, criteria_version="c1")
        self.assertEqual(out["level"], "L2")
        self.assertIsNone(out["winner"])

    def test_missing_budget_caps_at_l0(self):
        arms = {"single": {"passed": True, "tokens": 100, "chars": 100},
                "team": {"passed": True, "tokens": 300, "chars": 100}}
        out = verdict(arms, budget=0, criteria_version="c1")
        self.assertEqual(out["level"], "L0")
        self.assertIn("预算", "；".join(out["problems"]))

    def test_missing_criteria_version_caps_at_l0(self):
        arms = {"single": {"passed": True, "tokens": 100},
                "team": {"passed": True, "tokens": 300}}
        out = verdict(arms, budget=1000, criteria_version="")
        self.assertEqual(out["level"], "L0")

    def test_single_arm_is_not_a_comparison(self):
        arms = {"single": {"passed": True, "tokens": 100}}
        out = verdict(arms, budget=1000, criteria_version="c1")
        self.assertEqual(out["level"], "L0")
        self.assertIn("候选集", "；".join(out["problems"]))

    def test_failed_arm_is_not_qualified(self):
        arms = {"single": {"passed": False, "tokens": 1, "chars": 1},
                "team": {"passed": True, "tokens": 2, "chars": 2}}
        self.assertEqual(verdict(arms, budget=10, criteria_version="c")["level"], "不合格")

    def test_deltas_are_differences_against_baseline(self):
        arms = {"single": {"passed": True, "tokens": 100, "chars": 100},
                "team": {"passed": True, "tokens": 300, "chars": 200}}
        out = verdict(arms, budget=1000, criteria_version="c1")
        self.assertEqual(out["baseline"], "single")
        self.assertEqual(out["deltas"]["team"]["tokens"], 200)
        self.assertEqual(out["deltas"]["team"]["chars"], 100)

    def test_pareto_keeps_both_when_tradeoff(self):
        arms = {"a": {"tokens": 1, "chars": 1}, "b": {"tokens": 2, "chars": 2}}
        self.assertEqual(sorted(pareto(arms, {"tokens": -1, "chars": 1})), ["a", "b"])
        self.assertTrue(dominates({"tokens": 1, "chars": 1},
                                  {"tokens": 2, "chars": 1}, {"tokens": -1, "chars": 1}))


class BlindTest(unittest.TestCase):
    def _llm(self, first_score, second_score):
        def llm(messages, max_tokens=None):
            return json.dumps({"1": {d: first_score for d in
                                     ("结论", "证据", "取舍", "局限", "可执行")},
                               "2": {d: second_score for d in
                                     ("结论", "证据", "取舍", "局限", "可执行")}},
                              ensure_ascii=False)
        return llm

    def test_order_is_hidden_and_mapped_back(self):
        straight = blind_score("A", "B", self._llm(3, 0), flip=False)
        self.assertEqual(straight["first"]["结论"], 3)
        self.assertEqual(straight["order"], "straight")
        flipped = blind_score("A", "B", self._llm(3, 0), flip=True)
        self.assertEqual(flipped["first"]["结论"], 0, "翻过顺序后，原 A 拿到的是文档2的分")
        self.assertEqual(flipped["second"]["结论"], 3)
        self.assertEqual(flipped["order"], "flipped")

    def test_malformed_scores_are_loud(self):
        with self.assertRaises(ValueError):
            blind_score("A", "B", lambda m, max_tokens=None: "不是 JSON", flip=False)
        with self.assertRaises(ValueError):
            blind_score("A", "B", self._llm(9, 0), flip=False)   # 9 分越界


if __name__ == "__main__":
    unittest.main()