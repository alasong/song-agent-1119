"""M3：常驻调度（drain）。红先：sa2/autonomy/daemon.py 还不存在。

判据：自动领取 approved 工单并跑完；空队列退出；重启不重跑已完成。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sa2.autonomy.backlog import Backlog, Goal
from sa2.autonomy.daemon import drain
from sa2.core.judge import Judge
from sa2.core.ledger import Ledger
from sa2.forge import criteria as fc

DIMS = ("correctness",)


def make_judge() -> Judge:
    judge = Judge(authority=("leader",))
    judge.register(fc.tested(fc.propose_sections("章节齐全", ["## 一、a", "## 二、b"], DIMS)),
                   proposer="leader")
    return judge


def make_goal(text: str, **kw) -> Goal:
    base = dict(text=text, dims=DIMS, criteria=("章节齐全",), budget_tokens=10_000)
    base.update(kw)
    return Goal(**base)


def good_produce(role, stage, upstream, attempt, feedback="", requirements=""):
    return "## 一、a\n## 二、b\n"


class DaemonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.backlog = Backlog(self.root / "backlog.jsonl")
        self.ledger = Ledger(self.root / "ledger.jsonl")
        self.judge = make_judge()

    def tearDown(self):
        self.tmp.cleanup()

    def test_drains_approved_goals_then_exits(self):
        self.backlog.add(make_goal("写第一份"))
        self.backlog.add(make_goal("写第二份"))
        out = drain(self.backlog, self.ledger, self.judge, good_produce, {"correctness": "正确性"})
        self.assertEqual(out["ran"], 2)
        self.assertEqual(out["passed"], 2)
        self.assertEqual(self.ledger.count("daemon_start"), 1)
        self.assertEqual(self.ledger.count("daemon_stop"), 1)

    def test_restart_does_not_rerun_done_goals(self):
        self.backlog.add(make_goal("写第一份"))
        drain(self.backlog, self.ledger, self.judge, good_produce, {"correctness": "正确性"})
        out = drain(self.backlog, self.ledger, self.judge, good_produce, {"correctness": "正确性"})
        self.assertEqual(out["ran"], 0, "第二次启动不该再跑已完成的目标")

    def test_crash_leaves_the_unfinished_goal_for_restart(self):
        self.backlog.add(make_goal("第一份"))
        self.backlog.add(make_goal("第二份"))
        calls: list[int] = []

        def flaky(role, stage, upstream, attempt, feedback="", requirements=""):
            calls.append(1)
            if len(calls) == 2:
                raise SystemExit("模拟进程被杀")
            return good_produce(role, stage, upstream, attempt, feedback, requirements)

        with self.assertRaises(SystemExit):
            drain(self.backlog, self.ledger, self.judge, flaky, {"correctness": "正确性"})

        calls.clear()

        def good_recorded(role, stage, upstream, attempt, feedback="", requirements=""):
            calls.append(1)
            return good_produce(role, stage, upstream, attempt, feedback, requirements)

        out = drain(self.backlog, self.ledger, self.judge, good_recorded,
                    {"correctness": "正确性"})
        self.assertEqual(out["ran"], 1, "重启只该跑没做完的那一个")
        self.assertEqual(len(calls), 1, "已完成的不许重跑")

    def test_unapproved_self_goal_is_not_taken(self):
        self.backlog.add(make_goal("我自己想的", source="self", approved=False))
        out = drain(self.backlog, self.ledger, self.judge, good_produce, {"correctness": "正确性"})
        self.assertEqual(out["ran"], 0)


if __name__ == "__main__":
    unittest.main()