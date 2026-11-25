"""节点在 worker 进程里执行：每条派活的 pid 与主进程不同，账本带 node_id。

这是“支持各种量级”的关键路径：节点若只会在主进程里串行跑，规模就上不去。
"""
import os
import tempfile
import unittest
from pathlib import Path

from sa2.autonomy import tree
from sa2.autonomy.node_runner import make_runner
from sa2.core.judge import Judge
from sa2.core.ledger import Ledger
from sa2.forge import criteria as fc
from sa2.forge import dims as fd
from sa2.loop.workers import WorkerPool


def prompt_builder(role, stage, upstream, attempt, feedback="", requirements=""):
    return f"请写一遍 {stage}"


def make_judge() -> Judge:
    judge = Judge(authority=("leader",))
    judge.register(fc.tested(fc.propose_sections(
        "章节", ["## 一、a", "## 二、b"], ("correctness",))), proposer="leader")
    return judge


class NodeWorkerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.ledger = Ledger(root / "ledger.jsonl")
        self.pool = WorkerPool(root / "pool", self.ledger, workers=2, ttl=2.0).start()
        self.addCleanup(self.pool.stop)

    def node(self):
        return tree.Node("n1", "写一节草稿", dims=("correctness",), criteria=("章节",),
                         budget=100_000)

    def test_dispatch_runs_in_a_worker_process(self):
        out = make_runner(make_judge(), self.ledger, fd.VOCAB,
                          pool=self.pool, prompt_builder=prompt_builder)(self.node())
        self.assertTrue(out["ok"], out)
        leased = [e for e in self.ledger.read() if e["kind"] == "dispatch_leased"]
        self.assertGreaterEqual(len(leased), 1, "节点派活没有走 worker")
        self.assertNotEqual(leased[0]["payload"]["pid"], os.getpid(),
                            "派活必须在另一个进程里执行")

    def test_node_run_event_carries_id_and_dispatch_count(self):
        make_runner(make_judge(), self.ledger, fd.VOCAB,
                    pool=self.pool, prompt_builder=prompt_builder)(self.node())
        events = [e for e in self.ledger.read() if e["kind"] == "node_run"]
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        self.assertEqual(payload["id"], "n1")
        self.assertTrue(payload["worker"])
        self.assertGreaterEqual(payload["dispatches"], 1)

    def test_requires_produce_or_pool(self):
        with self.assertRaisesRegex(ValueError, "pool \\+ prompt_builder"):
            make_runner(make_judge(), self.ledger, fd.VOCAB)


if __name__ == "__main__":
    unittest.main()