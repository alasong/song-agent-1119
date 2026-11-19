"""交付自证检查：五条规则各一个用例，外加「现有产物必须红」这条试金石。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from xm import delivery

GOOD = """## 结论
把交付标准搬进 sa：1 个模块、5 条规则，全部可判红。

## 依据
- 选共用一套裸称规则 → 否掉了两处各写一份，上次就是这么漂的。
- 选先写检查再接线 → 现有产物先红，才能证明它不是摆设。

## 证据
- `tests/test_delivery_tool.py` exit 0；提交 2c1c6ca。
"""


class DeliveryCheckTest(unittest.TestCase):
    def test_good_delivery_passes(self):
        result = delivery.check(GOOD)
        self.assertTrue(result["ok"], result["missing"])

    def test_missing_section_is_red(self):
        text = GOOD.split("## 证据")[0]
        result = delivery.check(text)
        self.assertFalse(result["ok"])
        self.assertTrue(any("R1" in m and "证据" in m for m in result["missing"]))

    def test_conclusion_without_reading_is_red(self):
        text = GOOD.replace("1 个模块、5 条规则，全部可判红。", "已完成，效果很好。")
        result = delivery.check(text)
        self.assertFalse(result["ok"])
        self.assertTrue(any("R2" in m for m in result["missing"]))

    def test_more_than_three_reasons_is_red(self):
        text = GOOD.replace("- 选先写检查再接线", "- 甲\n- 乙\n- 丙\n- 选先写检查再接线")
        result = delivery.check(text)
        self.assertFalse(result["ok"])
        self.assertTrue(any("R3" in m and "超过" in m for m in result["missing"]))

    def test_reasons_without_any_rejection_is_red(self):
        text = GOOD.replace("- 选共用一套裸称规则 → 否掉了两处各写一份，上次就是这么漂的。",
                            "- 选共用一套裸称规则，因为省事。")
        result = delivery.check(text)
        self.assertFalse(result["ok"])
        self.assertTrue(any("否掉" in m for m in result["missing"]))

    def test_evidence_without_anchor_is_red(self):
        text = GOOD.replace("- `tests/test_delivery_tool.py` exit 0；提交 2c1c6ca。",
                            "- 测试都过了，放心。")
        result = delivery.check(text)
        self.assertFalse(result["ok"])
        self.assertTrue(any("R4" in m for m in result["missing"]))

    def test_bare_optimal_is_red(self):
        # 单独一行、同行没有读数：这才叫裸称
        text = GOOD.replace("## 证据", "这个方案是最优的。\n\n## 证据")
        result = delivery.check(text)
        self.assertFalse(result["ok"])
        self.assertTrue(any("R5" in m for m in result["missing"]))

    def test_quoted_discussion_is_allowed(self):
        text = GOOD.replace("全部可判红。", "全部可判红；「最优」这个词按 OPTIMALITY 的 L1/L2 改用。")
        self.assertTrue(delivery.check(text)["ok"])


class ExistingArtifactIsRedTest(unittest.TestCase):
    """试金石：上轮 sa 自己产出的交付，按新规则必须不合格。"""

    def test_real_deliverable_from_last_run_fails(self):
        candidates = sorted(Path.home().glob("xm-runs/*/sa-run-*/deliverable.md"))
        if not candidates:
            self.skipTest("没有历史交付物可测")
        text = candidates[-1].read_text(encoding="utf-8")
        result = delivery.check(text)
        self.assertFalse(result["ok"],
                         "历史交付都能过，说明这五条根本卡不住东西")
        self.assertTrue(any("R1" in m for m in result["missing"]))


if __name__ == "__main__":
    unittest.main()