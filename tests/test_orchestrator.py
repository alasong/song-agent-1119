"""V2 入口编排：只分发不生产；每个节点短命；上限到了就拒绝而不是硬撑。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sa2.autonomy import tree
from sa2.autonomy.orchestrator import Orchestrator
from sa2.core.ledger import Ledger


def runner(node):
    return {"ok": True, "text": f"## {node.id}\n正文", "evidence": ("S1",)}


def splitter(n):
    def split(node):
        return [{"goal": f"子{i}", "dims": ("correctness",), "criteria": ("c",),
                 "headings": 0} for i in range(1, n + 1)]
    return split


def root(headings=4, budget=100_000):
    return tree.Node("r", "写一份报告", dims=("correctness",), criteria=("c",),
                     budget=budget, headings=headings)


class OrchestratorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Ledger(Path(self.tmp.name) / "l.jsonl")

    def test_tree_expands_then_leaves_run(self):
        node = root(headings=4)
        out = Orchestrator(runner=runner, splitter=splitter(4), ledger=self.ledger).run(node)
        self.assertTrue(out["ok"], out["problems"])
        self.assertEqual(out["nodes"], 5)
        self.assertEqual(node.unit, tree.RECURSE)
        self.assertIn("## r.1", out["artifact"])
        self.assertEqual(node.evidence, ("S1",), "证据要跟着产物往上汇总")
        self.assertEqual(self.ledger.count("node_started"), 5)
        self.assertEqual(self.ledger.count("node_done"), 5)

    def test_fan_out_cap_is_refused_not_truncated(self):
        out = Orchestrator(runner=runner, splitter=splitter(13), ledger=self.ledger).run(
            root(headings=4))
        self.assertFalse(out["ok"])
        self.assertTrue(any("扇出" in p for p in out["problems"]), out["problems"])
        self.assertEqual(self.ledger.count("tree_refused"), 1)

    def test_failed_child_fails_the_parent(self):
        def flaky(node):
            out = runner(node)
            if node.id == "r.2":
                out["ok"] = False
            return out

        node = root(headings=4)
        out = Orchestrator(runner=flaky, splitter=splitter(4)).run(node)
        self.assertFalse(out["ok"])
        self.assertEqual(node.status, "failed")

    def test_nodes_cap_is_enforced(self):
        with mock.patch.dict(os.environ, {"XM_SA2_TREE_NODES_MAX": "2"}):
            out = Orchestrator(runner=runner, splitter=splitter(2)).run(root(headings=4))
        self.assertFalse(out["ok"])
        self.assertTrue(any("节点数" in p for p in out["problems"]), out["problems"])

    def test_entry_produces_no_content_itself(self):
        """入口只有路由与装配：叶子全挂时，它自己不会补正文。"""
        def dead(node):
            return {"ok": False, "text": "", "evidence": ()}

        node = root(headings=4)
        out = Orchestrator(runner=dead, splitter=splitter(2)).run(node)
        self.assertFalse(out["ok"])
        self.assertEqual(out["artifact"], "", "入口不许替叶子写内容")


if __name__ == "__main__":
    unittest.main()