"""D3 交付入口：先一个人干，判不过再组队。三条触发条件都要能判红/判绿。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm import deliver


def single(ok: bool, calls: list):
    def fn():
        calls.append("single")
        return {"passed": ok, "rounds": 3, "chars": 3000, "artifact": "a.md"}
    return fn


def org(ok: bool, calls: list):
    def fn():
        calls.append("org")
        return {"passed": ok, "rounds": 1, "chars": 3500, "artifact": "b.md"}
    return fn


class DecisionTest(unittest.TestCase):
    def test_single_pass_does_not_hire(self):
        calls: list[str] = []
        report = deliver.deliver("目标", {}, single(True, calls), org(True, calls))
        self.assertEqual(calls, ["single"], "单 agent 过了就不该组队——组队是备选不是默认")
        self.assertEqual(report["mode"], "single")
        self.assertFalse(report["org_called"])
        self.assertTrue(report["passed"])

    def test_single_fail_escalates(self):
        calls: list[str] = []
        report = deliver.deliver("目标", {}, single(False, calls), org(True, calls))
        self.assertEqual(calls, ["single", "org"])
        self.assertEqual(report["mode"], "org")
        self.assertEqual(report["attempts"][1]["via"], "escalation")
        self.assertTrue(report["passed"])

    def test_two_skill_domains_hire_upfront(self):
        calls: list[str] = []
        task = {"needs": ["research", "code"]}
        report = deliver.deliver("目标", task, single(True, calls), org(True, calls))
        self.assertEqual(calls, ["org"], "声明了跨域就不该先单干")
        self.assertEqual(report["attempts"][0]["via"], "pre")
        self.assertIn("2 个技能域", report["decision"]["reasons"][0])

    def test_irreversible_stakes_hire_upfront(self):
        calls: list[str] = []
        deliver.deliver("目标", {"stakes": "irreversible"}, single(True, calls), org(True, calls))
        self.assertEqual(calls, ["org"])

    def test_duplicate_needs_do_not_count_as_two_domains(self):
        self.assertEqual(deliver.pre_triggers({"needs": ["code", "code"]}), [])

    def test_both_fail_reports_failure_honestly(self):
        calls: list[str] = []
        report = deliver.deliver("目标", {}, single(False, calls), org(False, calls))
        self.assertFalse(report["passed"], "两次都不过就必须报没过，不能报成成功")
        self.assertEqual(len(report["attempts"]), 2)


if __name__ == "__main__":
    unittest.main()