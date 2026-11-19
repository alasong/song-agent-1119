"""结构化工单（设计文档 §6）的验收测试。

这是 M0b 实验的验收判据：Executor 必须让本文件全绿，且不得修改本文件。
"""
import unittest

from xm.ticket import Ticket, TicketError


class TicketTest(unittest.TestCase):
    def _valid(self, **over):
        base = {
            "id": "T1",
            "kind": "task",
            "sender": "planner",
            "receiver": "executor",
            "goal": "实现 A",
            "evidence": [],
        }
        base.update(over)
        return base

    def test_minimal_valid(self):
        t = Ticket.parse(self._valid())
        self.assertEqual(t.id, "T1")
        self.assertEqual(t.kind, "task")
        self.assertEqual(t.to_dict()["receiver"], "executor")

    def test_missing_required_field(self):
        payload = self._valid()
        del payload["goal"]
        with self.assertRaises(TicketError):
            Ticket.parse(payload)

    def test_unknown_kind_rejected(self):
        with self.assertRaises(TicketError):
            Ticket.parse(self._valid(kind="随便"))

    def test_fact_requires_evidence(self):
        with self.assertRaises(TicketError):
            Ticket.parse(self._valid(kind="fact", evidence=[]))
        ok = Ticket.parse(self._valid(kind="fact", evidence=["run-42"]))
        self.assertEqual(ok.evidence, ["run-42"])

    def test_roundtrip_is_stable(self):
        t = Ticket.parse(self._valid(evidence=["a", "b"]))
        again = Ticket.parse(t.to_dict())
        self.assertEqual(again.to_dict(), t.to_dict())


if __name__ == "__main__":
    unittest.main()