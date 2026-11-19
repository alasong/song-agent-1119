"""质量判据自身的测试：盲、可核对、fail-closed，三条缺一条就不算判据。"""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm import quality


def fake_llm(payload: dict):
    import json
    return lambda messages: json.dumps(payload, ensure_ascii=False)


def full_dims(value: int) -> dict:
    return {name: value for name in quality.DIMS}


class BlindTest(unittest.TestCase):
    def test_prompt_has_no_provenance(self):
        prompt = quality.blind_prompt([("甲" * 20), ("乙" * 20)])
        for leaked in ("单 agent", "组织", "sa", "daemon", ".md", "A 臂", "B 臂"):
            self.assertNotIn(leaked, prompt,
                             f"盲评提示里出现了出处线索：{leaked!r}（知道是谁写的就不叫盲评）")

    def test_prompt_contains_both_docs_and_rubric(self):
        prompt = quality.blind_prompt(["正文甲", "正文乙"])
        self.assertIn("文档 1", prompt)
        self.assertIn("文档 2", prompt)
        self.assertIn("正文甲", prompt)
        for name in quality.DIMS:
            self.assertIn(name, prompt)

    def test_order_is_deterministic_and_not_identity_forever(self):
        self.assertEqual(quality.order_for(2, 0), quality.order_for(2, 0))
        orders = {tuple(quality.order_for(2, seed)) for seed in range(20)}
        self.assertGreater(len(orders), 1, "顺序永远不变 = 位置偏差被固化")


class ParseTest(unittest.TestCase):
    def test_parses_valid(self):
        raw = '{"scores":[{"doc":1,"dims":%s,"note":"ok"},{"doc":2,"dims":%s,"note":""}]}' % (
            __import__("json").dumps(full_dims(3)), __import__("json").dumps(full_dims(1)))
        out = quality.parse_scores(raw, 2)
        self.assertEqual([o["total"] for o in out], [15, 5])

    def test_missing_dimension_is_error_not_zero(self):
        partial = {"结论": 3, "证据": 2}
        raw = '{"scores":[{"doc":1,"dims":%s},{"doc":2,"dims":%s}]}' % (
            __import__("json").dumps(partial), __import__("json").dumps(full_dims(1)))
        with self.assertRaises(quality.QualityError):
            quality.parse_scores(raw, 2)

    def test_out_of_range_is_error(self):
        raw = '{"scores":[{"doc":1,"dims":%s},{"doc":2,"dims":%s}]}' % (
            __import__("json").dumps(full_dims(9)), __import__("json").dumps(full_dims(1)))
        with self.assertRaises(quality.QualityError):
            quality.parse_scores(raw, 2)

    def test_wrong_count_is_error(self):
        raw = '{"scores":[{"doc":1,"dims":%s}]}' % __import__("json").dumps(full_dims(2))
        with self.assertRaises(quality.QualityError):
            quality.parse_scores(raw, 2)

    def test_garbage_is_error(self):
        with self.assertRaises(quality.QualityError):
            quality.parse_scores("我看不出差别", 2)


class JudgeMappingTest(unittest.TestCase):
    def test_maps_back_through_shuffle(self):
        order = quality.order_for(2, 7)
        # 让「文档 1」得低分、「文档 2」得高分
        payload = {"scores": [{"doc": 1, "dims": full_dims(0), "note": ""},
                              {"doc": 2, "dims": full_dims(3), "note": ""}]}
        result = quality.judge(["原文甲", "原文乙"], fake_llm(payload), seed=7)
        winner_index = order[1]           # 文档 2 对应原始下标
        self.assertEqual(result["winner"], winner_index)
        self.assertFalse(result["tie"])
        self.assertEqual(len(result["scores"]), 2)

    def test_tie_detected(self):
        payload = {"scores": [{"doc": 1, "dims": full_dims(2)},
                              {"doc": 2, "dims": full_dims(2)}]}
        result = quality.judge(["甲", "乙"], fake_llm(payload), seed=0)
        self.assertTrue(result["tie"])
        self.assertIsNone(result["winner"])

    def test_single_doc_refused(self):
        with self.assertRaises(quality.QualityError):
            quality.judge(["只有一份"], lambda m: "{}")


if __name__ == "__main__":
    unittest.main()