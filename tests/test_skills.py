"""「好 skill / 好 harness」分析的结构判据（人写）。

只能判结构与要素是否齐全，判不了观点对不对——这条限制不藏。
"""
import re
import unittest
from pathlib import Path

DOC = Path("runs/2026-11-19-skills/analysis.md")
SECTIONS = ["## 一、什么是好的 Agent Skill", "## 二、Harness 的最小骨架", "## 三、验收与陷阱"]


class SkillsAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(DOC.exists(), f"{DOC} 不存在")
        self.text = DOC.read_text(encoding="utf-8")

    def test_required_sections(self):
        for head in SECTIONS:
            self.assertIn(head, self.text)

    def test_at_least_five_skills_with_reason_and_counterexample(self):
        body = self.text.split("## 二")[0]
        items = re.findall(r"^\d+\.\s+\*\*.+?\*\*：", body, re.M)
        self.assertGreaterEqual(len(items), 5, f"只有 {len(items)} 条")
        for label in ("理由：", "反例："):
            self.assertIn(label, body)
        self.assertGreaterEqual(body.count("反例："), 3, "反例太少，缺少证伪面")

    def test_harness_table_has_components_and_failure_modes(self):
        body = self.text.split("## 二")[1].split("## 三")[0]
        rows = [l for l in body.splitlines() if l.strip().startswith("|")]
        self.assertGreaterEqual(len(rows), 7, "组件表至少 5 个数据行 + 表头 + 分隔")
        self.assertIn("失败模式", body)

    def test_pitfalls_at_least_four(self):
        body = self.text.split("## 三")[1]
        bullets = [l for l in body.splitlines() if l.strip().startswith(("-", "*"))]
        self.assertGreaterEqual(len(bullets), 4)

    def test_length(self):
        self.assertGreaterEqual(len(self.text), 2000, "内容过短，像占位")


if __name__ == "__main__":
    unittest.main()