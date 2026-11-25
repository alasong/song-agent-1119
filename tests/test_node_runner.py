"""节点运行器：叶子一次单角色环，小组走调用方给的编制；返回统一形状。"""
import tempfile
import unittest
from pathlib import Path

from sa2.autonomy import tree
from sa2.autonomy.node_runner import make_runner, plan_for_node
from sa2.core.gate import Declaration
from sa2.core.judge import Judge
from sa2.core.ledger import Ledger
from sa2.forge import criteria as fc
from sa2.forge import dims as fd


def make_judge() -> Judge:
    judge = Judge(authority=("leader",))
    judge.register(fc.tested(fc.propose_sections("章节", ["## 一、a"], ("correctness",))),
                   proposer="leader")
    return judge


def produce(role, stage, upstream, attempt, feedback="", requirements=""):
    if role.kind == "verifier":
        return ""
    return "## 一、a\n正文"


class NodeRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Ledger(Path(self.tmp.name) / "l.jsonl")

    def node(self, unit="leaf"):
        return tree.Node("n1", "写一节", dims=("correctness",), criteria=("章节",),
                         budget=100_000, unit=unit)

    def test_leaf_uses_single_plan_and_runs_once(self):
        plan, decl = plan_for_node(self.node())
        self.assertEqual(len(plan.roles), 1)
        self.assertEqual(len(plan.stages), 1)
        self.assertEqual([s.gate_criteria for s in plan.stages], [("章节",)])
        self.assertEqual(decl.budget_tokens, 100_000)

        out = make_runner(make_judge(), self.ledger, fd.VOCAB, produce)(self.node())
        self.assertTrue(out["ok"], out)
        self.assertIn("## 一、a", out["text"])
        self.assertEqual(self.ledger.count("dispatch"), 1, "叶子只派一次活")

    def test_group_requires_a_plan_factory(self):
        with self.assertRaisesRegex(ValueError, "team_plan_factory"):
            plan_for_node(self.node(unit="group"))

    def test_group_uses_the_given_team_plan(self):
        calls: list[Declaration] = []

        def factory(decl):
            calls.append(decl)
            from sa2.forge import org
            return org.parse_plan("写一节", '{"roles": ['
                                  '{"name":"写","kind":"executor","duty":"写","criteria":"齐","budget":10},'
                                  '{"name":"判","kind":"verifier","duty":"判","criteria":"检","budget":10},'
                                  '{"name":"整","kind":"curator","duty":"整","criteria":"序","budget":10}],'
                                  '"stages": ['
                                  '{"name":"起草","output":"草稿","roles":["写","整"],"gate_criteria":["章节"]},'
                                  '{"name":"定稿","output":"终稿","roles":["写","判"],"gate_criteria":["章节"]}]}',
                                  available_criteria=["章节"])

        node = self.node(unit="group")
        plan, _ = plan_for_node(node, factory)
        self.assertEqual(len(plan.roles), 3)
        self.assertEqual(len(calls), 1, "工厂只按声明问一次")

        out = make_runner(make_judge(), self.ledger, fd.VOCAB, produce,
                          team_plan_factory=factory)(node)
        self.assertTrue(out["ok"], out)


if __name__ == "__main__":
    unittest.main()