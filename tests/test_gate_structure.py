"""结构判据：给人看的交付要有表格与条目，不能整篇平铺。"""
import unittest

from sa2.core.gate import check_structure
from sa2.core.gate_profiles import PROFILES, check_task, delivery_specs, get


class CheckStructureTest(unittest.TestCase):
    def test_flat_prose_is_rejected(self):
        problems = check_structure("这是一段平铺的文字。" * 20,
                                   {"min_tables": 1, "min_bullets": 1})
        self.assertEqual(len(problems), 2, problems)

    def test_tables_and_bullets_pass(self):
        text = "## 结论\n- 要点一\n- 要点二\n\n| 列 | 值 |\n|---|---|\n| a | 1 |\n"
        self.assertEqual(check_structure(text, {"min_tables": 2, "min_bullets": 2}), [])

    def test_thresholds_come_from_spec(self):
        text = "- 只有一条\n"
        self.assertEqual(check_structure(text, {"min_bullets": 1}), [])
        self.assertTrue(check_structure(text, {"min_bullets": 2}))


class StructuredProfileTest(unittest.TestCase):
    def test_structured_profile_has_no_citation_gate(self):
        specs = delivery_specs(get("structured"), book="b.jsonl", volume_min=1200)
        names = [s["name"] for s in specs]
        self.assertNotIn("交付·引用", names)
        self.assertIn("交付·结构", names)

    def test_structure_spec_carries_thresholds(self):
        specs = delivery_specs(get("structured"), book="b.jsonl", volume_min=1200)
        spec = next(s for s in specs if s["name"] == "交付·结构")["spec"]
        self.assertEqual(spec["min_tables"], 8)
        self.assertEqual(spec["min_bullets"], 5)

    def test_structured_needs_no_test_command(self):
        self.assertEqual(check_task(PROFILES["structured"], test_cmd=None), [])

    def test_default_and_annotation_keep_their_shape(self):
        for name in ("default", "annotation"):
            names = [s["name"] for s in delivery_specs(PROFILES[name], book="b", volume_min=1200)]
            self.assertNotIn("交付·结构", names, "既有档不加结构门，避免误杀存量交付")


if __name__ == "__main__":
    unittest.main()
