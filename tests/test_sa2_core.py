"""sa2 L0 自检：判定权、预算闸、账本、四道门。

这里测的是「不许发生」的事——越权登记、未自测登记、静默失败被放过。
它们比「功能能用」重要：功能坏了看得见，越权坏了看不见。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from sa2.core import gate
from sa2.core.budget import Budget
from sa2.core.gate import Declaration
from sa2.core.judge import CriteriaError, Criterion, Judge, Unauthorized
from sa2.core.ledger import Ledger

VOCAB = {"correctness": "正确性", "test_quality": "测试质量"}


def sections(name="三段齐全", required=("## 一、a", "## 二、b", "## 三、c"), dims=("correctness",)):
    return Criterion(name=name, kind="sections", spec={"required": list(required)},
                     dims=tuple(dims), self_tested=True)


class LedgerTest(unittest.TestCase):
    def test_append_only_and_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = Ledger(Path(tmp) / "l.jsonl")
            led.append("start", "sa", {"x": 1})
            led.append("done", "sa")
            events = led.read()
            self.assertEqual([e["kind"] for e in events], ["start", "done"])
            self.assertEqual(led.count("start"), 1)
            self.assertFalse(hasattr(led, "delete"), "账本不许有删除入口")

    def test_corrupt_line_is_visible_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "l.jsonl"
            path.write_text('{"kind":"ok"}\nnot json\n', encoding="utf-8")
            events = Ledger(path).read()
            self.assertEqual(events[0]["kind"], "ok")
            self.assertEqual(events[1]["kind"], "corrupt")


class BudgetTest(unittest.TestCase):
    def test_char_estimate_when_no_usage(self):
        b = Budget(100)
        b.note("x" * 40)
        self.assertEqual(b.spent, 10)
        self.assertFalse(b.exact)

    def test_real_usage_wins(self):
        usage = [{"total_tokens": 7}]
        b = Budget(100, usage=usage)
        b.note("x" * 40)
        b.note("y" * 40)
        usage.append({"total_tokens": 9})
        self.assertEqual(b.spent, 16)
        self.assertTrue(b.exact)

    def test_exhausted_and_why(self):
        b = Budget(5, usage=[{"total_tokens": 6}])
        self.assertTrue(b.exhausted())
        self.assertIn("预算用尽", b.why("成稿"))


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.judge = Judge(authority=("leader",))

    def test_generator_cannot_register(self):
        with self.assertRaises(Unauthorized):
            self.judge.register(sections(), proposer="generator")

    def test_untested_criterion_is_refused(self):
        crit = Criterion(name="未测", kind="sections", spec={"required": ["## 一"]},
                         dims=("correctness",), self_tested=False)
        with self.assertRaises(CriteriaError):
            self.judge.register(crit, proposer="leader")

    def test_unknown_kind_is_refused(self):
        crit = Criterion(name="怪形态", kind="vibes", spec={}, dims=("correctness",),
                         self_tested=True)
        with self.assertRaises(CriteriaError):
            self.judge.register(crit, proposer="leader")

    def test_sections_ignores_headings_inside_fences(self):
        self.judge.register(sections(), proposer="leader")
        fake = "```\n## 一、a\n## 二、b\n## 三、c\n```"
        verdict = self.judge.run("三段齐全", fake)
        self.assertFalse(verdict.ok)
        self.assertEqual(len(verdict.problems), 3)

    def test_sections_passes_only_with_exact_lines(self):
        self.judge.register(sections(), proposer="leader")
        good = "## 一、a\n## 二、b\n## 三、c\n"
        self.assertTrue(self.judge.run("三段齐全", good).ok)
        near = "## 一、a（补充）\n## 二、b\n## 三、c\n"
        self.assertFalse(self.judge.run("三段齐全", near).ok, "标题带尾巴不算同一节")

    def test_regex_and_exec_and_callable(self):
        self.judge.register(Criterion("有读数", "regex", {"patterns": [r"重合率=\d"]},
                                      ("correctness",), True), proposer="leader")
        self.judge.register(Criterion("命令过", "exec", {"cmd": [sys.executable, "-c", "pass"]},
                                      ("correctness",), True), proposer="leader")
        self.judge.register(Criterion("回调过", "callable",
                                      {"target": "tests.test_sa2_core:_always_ok"},
                                      ("correctness",), True), proposer="leader")
        self.assertTrue(self.judge.run("有读数", "重合率=0.9").ok)
        self.assertFalse(self.judge.run("有读数", "重合率很高").ok)
        self.assertTrue(self.judge.run("命令过", "任意").ok)
        self.assertTrue(self.judge.run("回调过", "任意").ok)

    def test_unregistered_criterion_is_a_red_verdict_not_an_exception(self):
        verdict = self.judge.run("不存在", "x")
        self.assertFalse(verdict.ok)
        self.assertIn("未登记", verdict.problems[0])

    def test_executed_is_recorded(self):
        self.judge.register(sections(), proposer="leader")
        self.judge.run("三段齐全", "## 一、a")
        self.assertEqual(self.judge.executed(), {"三段齐全"})

    def test_persist_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "criteria.json"
            j1 = Judge(authority=("leader",), path=path)
            j1.register(sections(), proposer="leader")
            j2 = Judge(authority=("leader",), path=path)
            self.assertEqual(j2.names(), ["三段齐全"])
            self.assertTrue(j2.run("三段齐全", "## 一、a\n## 二、b\n## 三、c").ok)


class GateTest(unittest.TestCase):
    def setUp(self):
        self.judge = Judge(authority=("leader",))
        self.judge.register(sections(), proposer="leader")

    def _decl(self, **kw):
        base = dict(goal="写点东西", dims=("correctness",), criteria=("三段齐全",),
                    budget_tokens=1000)
        base.update(kw)
        return Declaration(**base)

    def test_declaration_needs_dims_criteria_and_budget(self):
        problems = gate.check_declaration(self._decl(dims=(), criteria=(), budget_tokens=0), VOCAB)
        self.assertEqual(len(problems), 3, problems)

    def test_dimension_outside_vocab_is_refused(self):
        problems = gate.check_declaration(self._decl(dims=("vibes",)), VOCAB)
        self.assertTrue(any("词表外" in p for p in problems))

    def test_criteria_must_be_registered_and_cover_declared_dims(self):
        problems = gate.check_criteria(self.judge, self._decl(criteria=("没登记",)))
        self.assertTrue(any("未登记" in p for p in problems))
        problems = gate.check_criteria(self.judge, self._decl(dims=("test_quality",)))
        self.assertTrue(any("未声明的维度" in p for p in problems))

    def test_evidence_must_be_locatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.md"
            path.write_text("l1\nl2\n", encoding="utf-8")
            self.assertEqual(gate.check_evidence([f"{path}:2", "x=1", "$ ls"]), [])
            self.assertTrue(gate.check_evidence(["见附件"])[0].startswith("证据不可定位"))
            self.assertTrue(gate.check_evidence([f"{path}:99"])[0].startswith("证据行号超出"))
            self.assertTrue(gate.check_evidence([f"{tmp}/nope.md:1"])[0].startswith("证据路径不存在"))

    def test_silent_failure_when_dimension_has_no_criterion(self):
        decl = self._decl(dims=("correctness", "test_quality"))
        problems = gate.check_silent_failure(self.judge, decl, {"三段齐全"})
        self.assertTrue(any("test_quality" in p for p in problems))

    def test_silent_failure_when_criterion_never_ran(self):
        decl = self._decl()
        problems = gate.check_silent_failure(self.judge, decl, set())
        self.assertTrue(any("从未执行" in p for p in problems))

    def test_preflight_is_one_gate(self):
        ok = gate.pre_flight(self._decl(), self.judge, VOCAB)
        self.assertTrue(ok["ok"], ok)
        bad = gate.pre_flight(self._decl(criteria=("没登记",)), self.judge, VOCAB)
        self.assertFalse(bad["ok"])


def _always_ok(text):
    return []


if __name__ == "__main__":
    unittest.main()

class CriteriaReuseTest(unittest.TestCase):
    """跨运行复用：同形判据可以复用，但别轮的维度声明不许跟着进来。"""

    def test_same_shape_with_different_dims_is_not_reused(self):
        judge = Judge(authority=("leader",))
        first = Criterion(name="交付·章节", kind="sections", spec={"required": ["## 一"]},
                          dims=("correctness", "maintainability"), self_tested=True)
        judge.register(first, proposer="leader")
        incoming = Criterion(name="交付·章节", kind="sections", spec={"required": ["## 一"]},
                             dims=("correctness",), self_tested=True)
        got = judge.register(incoming, proposer="leader")
        self.assertEqual(got.dims, ("correctness",), "别轮的维度声明不该留在这一轮身上")
        self.assertEqual(got.version, 2, "换了维度就是换了判据，要升版本")

    def test_same_shape_and_dims_is_idempotent(self):
        judge = Judge(authority=("leader",))
        crit = Criterion(name="交付·章节", kind="sections", spec={"required": ["## 一"]},
                         dims=("correctness",), self_tested=True)
        judge.register(crit, proposer="leader")
        again = judge.register(crit, proposer="leader")
        self.assertEqual(again.version, 1)
