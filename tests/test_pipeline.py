"""阶段准出流水线验收测试（M0b-3 第二部分）。"""
import unittest

from xm.bus import Bus
from xm.gates import GateChain
from xm.pipeline import Pipeline
from xm.ticket import Ticket


def make(tid="T1", sender="planner", receiver="executor"):
    return Ticket.parse({
        "id": tid, "kind": "task", "sender": sender, "receiver": receiver,
        "goal": "实现 A", "evidence": [],
    })


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.bus = Bus()
        self.pipe = Pipeline(self.bus, GateChain())

    def test_happy_path_completes(self):
        self.bus.submit(make())
        self.pipe.run("T1", artifacts={
            "需求分解": {"判据": True},
            "设计": {"契约": True},
            "实现": {"判据跑过": True},
            "定位": {"复现用例": True},
            "运维": {"回滚演练": True},
        })
        self.assertEqual(self.bus.status("T1"), "completed")

    def test_gate_failure_rejects_and_returns(self):
        self.bus.submit(make())
        with self.assertRaises(Exception):
            self.pipe.run("T1", artifacts={
                "需求分解": {"判据": True},
                "设计": {"契约": True},
                "实现": {},  # 缺准出项
            })
        self.assertEqual(self.bus.status("T1"), "rejected")
        self.assertEqual([t.id for t in self.bus.inbox("planner")], ["T1"])

    def test_unknown_ticket_raises(self):
        with self.assertRaises(Exception):
            self.pipe.run("T404", artifacts={})


if __name__ == "__main__":
    unittest.main()