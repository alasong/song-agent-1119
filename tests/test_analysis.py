"""商业分析类交付的结构验收（M0b-5）。

说明：这类任务没法机检「结论对不对」，只能机检「结构是否完整、要素是否齐全」。
内容质量由人判——这条限制写在这里，不藏。
"""
import re
import unittest
from pathlib import Path

DOC = Path("docs/ai-money.md")
SECTIONS = ["## 结论", "## 候选切入点", "## 90 天行动", "## 反证条件"]
LABELS = ["客户：", "定价：", "证据：", "风险："]


class AnalysisTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(DOC.exists(), "docs/ai-money.md 不存在")
        self.text = DOC.read_text(encoding="utf-8")

    def test_required_sections(self):
        for head in SECTIONS:
            self.assertIn(head, self.text)

    def test_at_least_five_entries_with_all_fields(self):
        blocks = re.split(r"^### 切入点", self.text, flags=re.M)[1:]
        self.assertGreaterEqual(len(blocks), 5, f"只有 {len(blocks)} 个切入点")
        for i, block in enumerate(blocks, 1):
            for label in LABELS:
                self.assertIn(label, block, f"第 {i} 个切入点缺 {label}")

    def test_action_plan_has_30_60_90(self):
        body = self.text.split("## 90 天行动")[1].split("## 反证条件")[0]
        for mark in ("30", "60", "90"):
            self.assertIn(mark, body)

    def test_counter_conditions_at_least_two(self):
        body = self.text.split("## 反证条件")[1]
        bullets = [l for l in body.splitlines() if l.strip().startswith(("-", "*"))]
        self.assertGreaterEqual(len(bullets), 2)

    def test_length(self):
        self.assertGreaterEqual(len(self.text), 1500, "内容过短，像占位")


if __name__ == "__main__":
    unittest.main()