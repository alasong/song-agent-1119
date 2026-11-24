"""W0 第一片内环：确定性渲染 + 外置判定权。红先：两个模块都不存在。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sa2.core.cost_check import check
from sa2.loop.cost_page import render


class CostPageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.tmp.name) / "run"
        self.run_dir.mkdir()
        (self.run_dir / "readings.json").write_text(json.dumps({
            "budget": {"spent": 1234},
            "rejects": 2,
            "redone": ["起草", "成稿"],
            "chars": 500,
        }, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_render_matches_the_ledger(self):
        page = render(self.run_dir)
        self.assertEqual(page, {"tokens": 1234, "rejects": 2, "redone_count": 2})
        self.assertEqual(check(page, self.run_dir), [])

    def test_structurally_complete_but_wrong_numbers_are_red(self):
        page = render(self.run_dir)
        page["tokens"] += 1
        problems = check(page, self.run_dir)
        self.assertTrue(problems, "数字错必须判红，这是 L2 抗冒充的那条")
        self.assertIn("tokens", "；".join(problems))

    def test_missing_field_is_red(self):
        page = render(self.run_dir)
        page.pop("rejects")
        self.assertTrue(check(page, self.run_dir))

    def test_render_is_deterministic(self):
        self.assertEqual(render(self.run_dir), render(self.run_dir), "同输入必同输出")
        self.assertEqual(render(self.run_dir)["tokens"], 1234)

    def test_non_object_page_is_red(self):
        self.assertEqual(check(None, self.run_dir), ["交付物不是对象"])


if __name__ == "__main__":
    unittest.main()