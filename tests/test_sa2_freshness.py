"""时效自检的判据：不许拿老数据当结果，也不许用占位符冒充来源。

这三条来自领导的同一句话：「不管什么原因，也不能拿老数据给我结果吧，自己不能看出异常么」。
它不依赖任何外部能力——只用系统时间和交付里写的日期。
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2.core.freshness import dates, stale_problems

TODAY = date(2026, 11, 20)


class FreshnessTest(unittest.TestCase):
    def check(self, text: str) -> list[str]:
        return stale_problems(text, today=TODAY)

    def test_old_data_under_a_latest_heading_is_red(self):
        problems = self.check("## 一、最新进展\n- 某框架提出于 2025-05-06，此后无更新。")
        self.assertTrue(any("R3" in p for p in problems), problems)
        self.assertTrue(any("563" in p for p in problems), f"读数要写清多少天：{problems}")

    def test_latest_claim_without_any_date_is_red(self):
        problems = self.check("## 一、最新进展\n- 近期讨论集中在推理时扩展。")
        self.assertTrue(any("R2" in p for p in problems), problems)

    def test_no_date_and_no_claim_is_fine(self):
        self.assertEqual(self.check("## 一、方案\n- 先跑基线，再动一处。"), [])

    def test_placeholder_citation_is_red(self):
        problems = self.check("## 一、最新进展\n| M-01 | arXiv:2405.xxxxx | 2026-10-01 |")
        self.assertTrue(any("R1" in p for p in problems), problems)
        self.assertFalse(any("R3" in p for p in problems), "日期新就不该报老")

    def test_future_date_is_red(self):
        problems = self.check("## 一、最新进展\n- 某工作发表于 2027-01-01。")
        self.assertTrue(any("R4" in p for p in problems), problems)

    def test_fresh_date_passes(self):
        self.assertEqual(self.check("## 一、最新进展\n- 上周发布的 2026-11-10 版本。"), [])

    def test_code_fence_is_not_a_claim(self):
        # 围栏里那些日期/占位符是示例，不是声称；围栏外的标题也不承诺「最新」
        text = "## 一、附录\n```\n2020-01-01 xxxx 待填\n```\n正文里没有日期。"
        self.assertEqual(self.check(text), [], "围栏里讨论日期/占位不算声称")

    def test_dates_are_parsed_in_several_shapes(self):
        got = dates("2026年11月 / 2026-11 / 2026.11.05")
        self.assertEqual([d.isoformat() for d in got], ["2026-11-01", "2026-11-01", "2026-11-05"])

    def test_reports_the_oldest_problem_first_by_rule_number(self):
        text = "## 一、最新进展\n| arXiv:xxxx | 2025-01-01 |"
        problems = self.check(text)
        self.assertTrue(problems[0].startswith("R1"), problems)


if __name__ == "__main__":
    unittest.main()