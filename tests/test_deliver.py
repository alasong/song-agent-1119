"""D3 交付入口：先一个人干，判不过再组队。三条触发条件都要能判红/判绿。

另外一条：判据过了不算交付完成——产物还得能自证（结论/依据/证据），
这就是 DNA #9 接进 passed 的地方。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm import deliver

GOOD = """## 结论
把标准搬进 sa：5 条规则、1 个模块，可判红。

## 依据
- 选先写检查再接线 → 否掉了只改文档的做法。
- 选共用一套规则 → 否掉两处各写一份。

## 证据
- `tests/test_deliver.py` exit 0；提交 2c1c6ca。
"""


class DeliverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.good = self.dir / "good.md"
        self.good.write_text(GOOD, encoding="utf-8")
        self.plain = self.dir / "plain.md"
        self.plain.write_text("## 一、随便写的\n正文，没有三段。\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def single(self, ok: bool, calls: list, artifact: Path | None = None):
        def fn():
            calls.append("single")
            return {"passed": ok, "rounds": 3, "chars": 3000,
                    "artifact": str(artifact or self.good)}
        return fn

    def org(self, ok: bool, calls: list):
        def fn():
            calls.append("org")
            return {"passed": ok, "rounds": 1, "chars": 3500, "artifact": str(self.good)}
        return fn


class DecisionTest(DeliverTest):
    def test_single_pass_does_not_hire(self):
        calls: list[str] = []
        report = deliver.deliver("目标", {}, self.single(True, calls), self.org(True, calls))
        self.assertEqual(calls, ["single"], "单 agent 过了就不该组队——组队是备选不是默认")
        self.assertEqual(report["mode"], "single")
        self.assertFalse(report["org_called"])
        self.assertTrue(report["passed"])

    def test_single_fail_escalates(self):
        calls: list[str] = []
        report = deliver.deliver("目标", {}, self.single(False, calls), self.org(True, calls))
        self.assertEqual(calls, ["single", "org"])
        self.assertEqual(report["mode"], "org")
        self.assertEqual(report["attempts"][1]["via"], "escalation")
        self.assertTrue(report["passed"])

    def test_two_skill_domains_hire_upfront(self):
        calls: list[str] = []
        report = deliver.deliver("目标", {"needs": ["research", "code"]},
                                 self.single(True, calls), self.org(True, calls))
        self.assertEqual(calls, ["org"], "声明了跨域就不该先单干")
        self.assertEqual(report["attempts"][0]["via"], "pre")
        self.assertIn("2 个技能域", report["decision"]["reasons"][0])

    def test_irreversible_stakes_hire_upfront(self):
        calls: list[str] = []
        deliver.deliver("目标", {"stakes": "irreversible"},
                        self.single(True, calls), self.org(True, calls))
        self.assertEqual(calls, ["org"])

    def test_duplicate_needs_do_not_count_as_two_domains(self):
        self.assertEqual(deliver.pre_triggers({"needs": ["code", "code"]}), [])

    def test_both_fail_reports_failure_honestly(self):
        calls: list[str] = []
        report = deliver.deliver("目标", {}, self.single(False, calls), self.org(False, calls))
        self.assertFalse(report["passed"], "两次都不过就必须报没过，不能报成成功")
        self.assertEqual(len(report["attempts"]), 2)


class DeliveryDutyTest(DeliverTest):
    """DNA #9：自证由系统拼，模型只写正文——所以正文没三段也应该是合格交付。"""

    def test_plain_body_gets_self_evidence_appended(self):
        calls: list[str] = []
        report = deliver.deliver("目标", {}, self.single(True, calls, self.plain),
                                 self.org(True, calls))
        self.assertTrue(report["criteria_passed"])
        self.assertTrue(report["passed"])
        text = self.plain.read_text(encoding="utf-8")
        self.assertIn("## 结论", text)
        self.assertIn("## 依据", text)
        self.assertIn("## 证据", text)
        self.assertTrue(report["delivery"]["ok"], report["delivery"]["missing"])

    def test_attach_is_idempotent(self):
        calls: list[str] = []
        deliver.deliver("目标", {}, self.single(True, calls, self.plain), self.org(True, calls))
        first = self.plain.read_text(encoding="utf-8")
        deliver.deliver("目标", {}, self.single(True, calls, self.plain), self.org(True, calls))
        second = self.plain.read_text(encoding="utf-8")
        self.assertEqual(first, second, "第二次交付不许把自证再叠一遍")
        self.assertEqual(second.count("## 结论"), 1)

    def test_model_written_sections_are_not_overwritten(self):
        self.plain.write_text(GOOD, encoding="utf-8")
        calls: list[str] = []
        deliver.deliver("目标", {}, self.single(True, calls, self.plain), self.org(True, calls))
        self.assertEqual(self.plain.read_text(encoding="utf-8"), GOOD,
                         "已经有了就不动：产物是证据，不许重写")


if __name__ == "__main__":
    unittest.main()