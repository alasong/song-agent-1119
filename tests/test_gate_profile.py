"""M2：门按任务类型分层。红先：sa2/core/gate_profiles.py 还不存在。

判据：标注型（无外部证据）不再被「引用≥3」误杀；工程型无测试即拒。
"""
from __future__ import annotations

import unittest

from sa2.core.gate_profiles import PROFILES, check_task, delivery_specs, get


class GateProfileTest(unittest.TestCase):
    def test_default_keeps_the_citation_gate(self):
        specs = delivery_specs(PROFILES["default"], book="b.jsonl", volume_min=1200)
        names = [s["name"] for s in specs]
        self.assertIn("交付·引用", names)
        citation = next(s for s in specs if s["name"] == "交付·引用")
        self.assertEqual(citation["spec"]["min"], 3)
        self.assertIn("交付·出处", names)

    def test_annotation_drops_citation_and_keeps_volume(self):
        specs = delivery_specs(PROFILES["annotation"], book="b.jsonl", volume_min=1200)
        names = [s["name"] for s in specs]
        self.assertNotIn("交付·引用", names, "标注型没有外部证据可引，不能被引用门槛误杀")
        self.assertNotIn("交付·出处", names)
        volume = next(s for s in specs if s["name"] == "交付·体量")
        self.assertEqual(volume["spec"]["min"], 200)

    def test_engineering_requires_a_test_command(self):
        self.assertTrue(check_task(PROFILES["engineering"], test_cmd=None))
        self.assertTrue(check_task(PROFILES["engineering"], test_cmd=[]))
        self.assertEqual(check_task(PROFILES["engineering"], test_cmd=["pytest", "-q"]), [])

    def test_annotation_needs_no_test_command(self):
        self.assertEqual(check_task(PROFILES["annotation"], test_cmd=None), [])

    def test_unknown_profile_is_loud(self):
        with self.assertRaises(KeyError):
            get("没有这个类型")


if __name__ == "__main__":
    unittest.main()