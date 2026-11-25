"""失败后节点级自动展开（变频的执行形态）：只在节点边界拆，预算按 30% 预留。

不是“中途改编制”：原节点判失败后，按章节/子任务新起子节点，子节点各自短命执行，
父节点只做装配；深度、扇出、节点数三个上限照旧生效。
"""
import tempfile
import unittest
from pathlib import Path

from sa2.autonomy import tree
from sa2.autonomy.orchestrator import Orchestrator
from sa2.core.ledger import Ledger


def splitter(node):
    return [{"goal": f"{node.id}.{i}", "dims": ("correctness",), "criteria": ("c",),
             "headings": 0} for i in (1, 2)]


def make_runner(fail_ids=("r",), seen=None):
    def runner(node):
        if seen is not None:
            seen.append(node.id)
        if node.id in fail_ids:
            return {"ok": False, "text": "", "evidence": (), "rejects": 2,
                    "failure_kinds": ["criteria_rejected"]}
        return {"ok": True, "text": f"## {node.id}\n正文", "evidence": ("S1",)}
    return runner


class ExpandOnFailureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Ledger(Path(self.tmp.name) / "l.jsonl")

    def node(self, budget=100_000, depth=0):
        return tree.Node("r", "写一节", dims=("correctness",), criteria=("c",),
                         budget=budget, depth=depth)

    def test_failed_leaf_is_split_and_parent_assembles(self):
        seen: list[str] = []
        node = self.node()
        out = Orchestrator(runner=make_runner(seen=seen), splitter=splitter,
                           ledger=self.ledger, expand_on_failure=True).run(node)
        self.assertTrue(out["ok"], out["problems"])
        self.assertEqual(out["nodes"], 3, "父 + 两个子")
        self.assertEqual(seen, ["r", "r.1", "r.2"])
        self.assertTrue(node.expanded)
        self.assertEqual(self.ledger.count("node_expanded"), 1)
        self.assertIn("## r.1", out["artifact"])

    def test_expansion_off_keeps_single_failure(self):
        node = self.node()
        out = Orchestrator(runner=make_runner(), splitter=splitter,
                           ledger=self.ledger).run(node)
        self.assertFalse(out["ok"])
        self.assertEqual(out["nodes"], 1)
        self.assertEqual(self.ledger.count("node_expanded"), 0)

    def test_depth_cap_prevents_expansion(self):
        node = self.node(depth=3)          # tree_depth_max=3
        out = Orchestrator(runner=make_runner(), splitter=splitter,
                           ledger=self.ledger, expand_on_failure=True).run(node)
        self.assertFalse(out["ok"])
        self.assertEqual(out["nodes"], 1, "深度上限处不许再拆")

    def test_budget_reserve_reaches_children(self):
        budgets: list[int] = []

        def runner(node):
            budgets.append(node.budget)
            if node.id == "r":
                return {"ok": False, "text": "", "evidence": (), "rejects": 2}
            return {"ok": True, "text": f"## {node.id}\n正文", "evidence": ("S1",)}

        Orchestrator(runner=runner, splitter=splitter, ledger=self.ledger,
                     expand_on_failure=True).run(self.node(budget=100_000))
        self.assertEqual(budgets[0], 100_000)
        self.assertEqual(budgets[1], 35_000, "两个子节点各拿 (100000-30000)/2")

    def test_fan_out_refusal_is_recorded_not_crashed(self):
        many = lambda node: [{"goal": f"{node.id}.{i}", "dims": ("correctness",),
                              "criteria": ("c",)} for i in range(13)]
        node = self.node()
        out = Orchestrator(runner=make_runner(), splitter=many, ledger=self.ledger,
                           expand_on_failure=True).run(node)
        self.assertFalse(out["ok"])
        self.assertEqual(self.ledger.count("node_expand_refused"), 1)
        self.assertTrue(any("扇出" in p for p in out["problems"]), out["problems"])


if __name__ == "__main__":
    unittest.main()