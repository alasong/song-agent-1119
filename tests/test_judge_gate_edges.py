"""判定权与开工契约的边界：判据自己坏了算不通过，声明的每个空子都要报出来。

`test_sa2_core` 盖了主路径；这里补 judge 的三种形态错误与执行异常，
以及 gate 的两道声明检查——「生成方不能给自己发毕业证」靠这些分支兜底。
"""
import unittest
from unittest import mock

from sa2.core.gate import Declaration, check_criteria, check_declaration
from sa2.core.judge import CriteriaError, Criterion, Judge
from sa2.forge import dims as fd

VOCAB = tuple(fd.VOCAB)


def probe_two(text, spec):
    """两参 callable：判据自带参数（门槛写在 spec 里，不写死在代码里）。"""
    return [] if spec.get("ok") else ["门槛没过"]


def probe_false(text):
    return False


def sections(required=("## 一、a",), dims=("correctness",), self_tested=True):
    return Criterion(name="章节", kind="sections", spec={"required": list(required)},
                     dims=dims, self_tested=self_tested)


class JudgeEdgeTest(unittest.TestCase):
    def setUp(self):
        self.judge = Judge(authority=("leader",))

    def test_unnamed_criterion_is_refused(self):
        with self.assertRaisesRegex(CriteriaError, "判据必须有名"):
            self.judge.register(Criterion(name="  ", kind="sections", spec={}), proposer="leader")

    def test_crashing_criterion_is_a_failure_not_a_pass(self):
        self.judge.register(sections(), proposer="leader")
        with mock.patch.object(Judge, "_run_sections", side_effect=RuntimeError("判据坏了")):
            verdict = self.judge.run("章节", "## 一、a\n正文")
        self.assertFalse(verdict.ok, "判据自己坏了不许静默放行")
        self.assertTrue(any("判据执行异常" in p for p in verdict.problems), verdict.problems)

    def test_callable_target_must_be_module_function(self):
        crit = Criterion(name="可回调", kind="callable", spec={"target": "没冒号"},
                         dims=("correctness",), self_tested=True)
        self.judge.register(crit, proposer="leader")
        self.assertTrue(any("module:function" in p
                            for p in self.judge.run("可回调", "正文").problems))

    def test_callable_returning_false_is_a_failure(self):
        crit = Criterion(name="可回调", kind="callable",
                         spec={"target": "tests.test_judge_gate_edges:probe_false"},
                         dims=("correctness",), self_tested=True)
        self.judge.register(crit, proposer="leader")
        self.assertTrue(any("不通过" in p for p in self.judge.run("可回调", "正文").problems))

    def test_callable_receives_spec_when_it_takes_two_args(self):
        spec = {"target": "tests.test_judge_gate_edges:probe_two", "ok": True}
        self.judge.register(Criterion(name="两参", kind="callable", spec=spec,
                                      dims=("correctness",), self_tested=True),
                            proposer="leader")
        self.assertTrue(self.judge.run("两参", "正文").ok)
        self.judge.register(Criterion(name="两参", kind="callable", spec={**spec, "ok": False},
                                      dims=("correctness",), self_tested=True),
                            proposer="leader")
        self.assertFalse(self.judge.run("两参", "正文").ok)

    def test_exec_without_cmd_is_a_failure(self):
        crit = Criterion(name="执行", kind="exec", spec={"cmd": []},
                         dims=("correctness",), self_tested=True)
        self.judge.register(crit, proposer="leader")
        self.assertTrue(any("缺少 cmd" in p for p in self.judge.run("执行", "正文").problems))


class DeclarationEdgeTest(unittest.TestCase):
    def test_missing_goal_is_reported(self):
        decl = Declaration(goal="   ", dims=("correctness",), criteria=("章节",), budget_tokens=100)
        self.assertIn("声明缺目标", check_declaration(decl, VOCAB))

    def test_duplicate_dimension_is_reported(self):
        decl = Declaration(goal="目标", dims=("correctness", "correctness"),
                           criteria=("章节",), budget_tokens=100)
        self.assertTrue(any("维度重复声明" in p for p in check_declaration(decl, VOCAB)))

    def test_untested_criterion_blocks_the_declaration(self):
        judge = Judge(authority=("leader",), require_self_tested=False)
        judge.register(sections(self_tested=False), proposer="leader")
        decl = Declaration(goal="目标", dims=("correctness",), criteria=("章节",), budget_tokens=100)
        self.assertTrue(any("没跑过三反例自测" in p for p in check_criteria(judge, decl)))

    def test_unsupported_criterion_kind_is_reported(self):
        judge = Judge(authority=("leader",))
        judge._items["坏判据"] = Criterion(name="坏判据", kind="未知形态", spec={},
                                           dims=("correctness",), self_tested=True)
        decl = Declaration(goal="目标", dims=("correctness",), criteria=("坏判据",), budget_tokens=100)
        self.assertTrue(any("形态不支持" in p for p in check_criteria(judge, decl)))

    def test_clean_declaration_has_no_problems(self):
        judge = Judge(authority=("leader",))
        judge.register(sections(), proposer="leader")
        decl = Declaration(goal="目标", dims=("correctness",), criteria=("章节",), budget_tokens=100)
        self.assertEqual(check_declaration(decl, VOCAB), [])
        self.assertEqual(check_criteria(judge, decl), [])


if __name__ == "__main__":
    unittest.main()