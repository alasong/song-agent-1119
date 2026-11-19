"""sa2 新增两层的自检：L2 编制规模决策、L3 目标来源，以及案例库接上消费者。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sa2.autonomy.backlog import Backlog, Goal
from sa2.autonomy.tick import tick
from sa2.core.gate import Declaration
from sa2.core.judge import Judge
from sa2.core.ledger import Ledger
from sa2.forge import criteria as fc
from sa2.forge import dims as fd
from sa2.forge import org as fo
from sa2.loop import size
from sa2.loop.pdca import PDCA
from sa2.memory.cases import CaseBook

VOCAB = fd.VOCAB
S1, S2 = "## 一、a", "## 二、b"


def decl(**over):
    base = dict(goal="写东西", dims=("correctness",), criteria=("一段齐全",),
                budget_tokens=100_000)
    base.update(over)
    return Declaration(**base)


def make_judge(criteria=(("一段齐全", [S1, S2]),)):
    judge = Judge(authority=("leader",))
    for name, required in criteria:
        judge.register(fc.tested(fc.propose_sections(name, required, ("correctness",))),
                       proposer="leader")
    return judge


class SizeTest(unittest.TestCase):
    def test_low_budget_is_single(self):
        self.assertEqual(size.decide(decl(budget_tokens=5_000)).scale, "single")

    def test_two_dims_is_team(self):
        d = size.decide(decl(dims=("correctness", "test_quality")))
        self.assertEqual(d.scale, "team")
        self.assertIn("维度", d.reason)

    def test_three_criteria_is_team(self):
        d = size.decide(decl(criteria=("a", "b", "c")))
        self.assertEqual(d.scale, "team")

    def test_single_by_default(self):
        self.assertEqual(size.decide(decl()).scale, "single")

    def test_single_plan_is_one_role_one_stage(self):
        plan = size.single_plan(decl())
        self.assertEqual(len(plan.roles), 1)
        self.assertEqual(len(plan.stages), 1)
        self.assertEqual(plan.stages[0].gate_criteria, ("一段齐全",))

    def test_team_without_plan_raises(self):
        with self.assertRaises(ValueError):
            size.plan_for(decl(dims=("correctness", "test_quality")))

    def test_single_plan_runs_through_the_loop(self):
        d = decl()
        plan, decision = size.plan_for(d)
        self.assertEqual(decision.scale, "single")
        calls = []

        def produce(role, stage, upstream, attempt, feedback=""):
            calls.append(stage)
            return f"{S1}\n{S2}\n"

        with tempfile.TemporaryDirectory() as tmp:
            pdca = PDCA(make_judge(), Ledger(Path(tmp) / "l.jsonl"), plan, produce, VOCAB)
            report = pdca.run(d)
        self.assertTrue(report["passed"], report)
        self.assertEqual(calls, ["交付"], "单人只该有一次派活")


class BacklogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.book = Backlog(Path(self.tmp.name) / "q.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def _goal(self, **over):
        base = dict(text="写方案", dims=("correctness",), criteria=("一段齐全",),
                    budget_tokens=30_000)
        base.update(over)
        return Goal(**base)

    def test_pick_and_mark_done(self):
        goal = self._goal()
        self.book.add(goal)
        self.assertEqual(self.book.pick().text, "写方案")
        self.book.mark(goal, "done")
        self.assertIsNone(self.book.pick())
        self.assertIn(goal.gid(), self.book.done_ids())

    def test_unapproved_self_goal_is_not_picked(self):
        self.book.add(self._goal(text="自己提的目标", source="self", approved=False))
        self.assertIsNone(self.book.pick(), "自助目标未批准不许领取")

    def test_approved_self_goal_is_picked(self):
        self.book.add(self._goal(text="自己提的目标", source="self", approved=True))
        self.assertIsNotNone(self.book.pick())

    def test_mark_unknown_goal_raises(self):
        with self.assertRaises(ValueError):
            self.book.mark(self._goal(text="不存在的"), "done")

    def test_ids_are_stable_across_instances(self):
        self.assertEqual(self._goal().gid(), self._goal().gid())


class TickTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.book = Backlog(self.root / "q.jsonl")
        self.judge = make_judge()
        self.ledger = Ledger(self.root / "l.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def _goal(self, **over):
        base = dict(text="写方案", dims=("correctness",), criteria=("一段齐全",),
                    budget_tokens=100_000)
        base.update(over)
        return Goal(**base)

    def test_no_goal_means_no_work(self):
        result = tick(self.book, self.ledger, self.judge, lambda *a, **k: "", VOCAB)
        self.assertFalse(result.ran)
        self.assertIn("没有可领取", result.reason)

    def test_goal_with_unregistered_criteria_does_not_start(self):
        self.book.add(self._goal(criteria=("没登记",)))
        result = tick(self.book, self.ledger, self.judge, lambda *a, **k: "", VOCAB)
        self.assertFalse(result.ran)
        self.assertIn("判据未登记", result.reason)
        self.assertIsNotNone(self.book.pick(), "没开工的目标不该被标成完成")

    def test_successful_tick_marks_done(self):
        self.book.add(self._goal())
        result = tick(self.book, self.ledger, self.judge,
                      lambda *a, **k: f"{S1}\n{S2}\n", VOCAB)
        self.assertTrue(result.ran)
        self.assertEqual(result.scale, "single")
        self.assertTrue(result.report["passed"], result.report)
        self.assertIsNone(self.book.pick())

    def test_failed_tick_marks_failed(self):
        self.book.add(self._goal())
        result = tick(self.book, self.ledger, self.judge,
                      lambda *a, **k: "什么都没有\n", VOCAB)
        self.assertTrue(result.ran)
        self.assertFalse(result.report["passed"])
        self.assertIsNone(self.book.pick(), "失败的目标不该回到 pending")


class CaseConsumerTest(unittest.TestCase):
    """案例库以前只写不读；这里钉住它真的进了重做提示词。"""

    ORG = json.dumps({
        "roles": [
            {"name": "规划", "kind": "planner", "duty": "拆", "criteria": "可验收", "budget": 10},
            {"name": "执行", "kind": "executor", "duty": "写", "criteria": "齐全", "budget": 20},
            {"name": "验证", "kind": "verifier", "duty": "只判", "criteria": "有结论", "budget": 5},
        ],
        "stages": [
            {"name": "起草", "output": "d", "roles": ["规划", "执行"], "gate_criteria": ["起草齐全"]},
            {"name": "成稿", "output": "f", "roles": ["执行", "验证"], "gate_criteria": ["成稿齐全"]},
        ],
    }, ensure_ascii=False)

    def test_prior_case_shows_up_in_the_retry_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = CaseBook(root / "cases.jsonl")
            cases.add("成稿", "缺章节：## 三、c", "补第三节再交")
            judge = Judge(authority=("leader",))
            for name, required in (("起草齐全", [S1, S2]), ("成稿齐全", [S1, S2, "## 三、c"])):
                judge.register(fc.tested(fc.propose_sections(name, required,
                                                             ("correctness",))), proposer="leader")
            seen = []

            def produce(role, stage, upstream, attempt, feedback=""):
                seen.append((stage, attempt, feedback))
                if role.kind != "executor":
                    return ""
                if stage == "成稿" and attempt == 1:
                    return f"{S1}\n{S2}\n"
                return f"{S1}\n{S2}\n## 三、c\n"

            plan = fo.parse_plan("目标", self.ORG)
            pdca = PDCA(judge, Ledger(root / "l.jsonl"), plan, produce, VOCAB, cases=cases)
            report = pdca.run(Declaration(goal="t", dims=("correctness",),
                                          criteria=("起草齐全", "成稿齐全"),
                                          budget_tokens=100_000))
            self.assertTrue(report["passed"], report)
            retry = next(item for item in seen if item[1] == 2)
            self.assertIn("历史案例", retry[2])
            self.assertIn("补第三节再交", retry[2])


if __name__ == "__main__":
    unittest.main()