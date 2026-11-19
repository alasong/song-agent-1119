"""消息总线验收测试（M0b-2）。

覆盖面（故意不含全部规格）：submit / inbox / claim / complete / reject / stats。
规格里还有两条**测试不覆盖**的要求，见实验任务书：幂等、history 只增不改。
"""
import unittest

from xm.bus import Bus, BusError
from xm.ticket import Ticket


def make(tid="T1", sender="planner", receiver="executor", kind="task", evidence=None):
    return Ticket.parse({
        "id": tid,
        "kind": kind,
        "sender": sender,
        "receiver": receiver,
        "goal": "实现 A",
        "evidence": evidence or [],
    })


class BusTest(unittest.TestCase):
    def setUp(self):
        self.bus = Bus()

    def test_submit_and_inbox(self):
        t = make()
        self.bus.submit(t)
        self.assertEqual([x.id for x in self.bus.inbox("executor")], ["T1"])
        self.assertEqual(self.bus.inbox("planner"), [])

    def test_claim_moves_out_of_inbox(self):
        self.bus.submit(make())
        self.bus.claim("executor", "T1")
        self.assertEqual(self.bus.status("T1"), "in_progress")
        self.assertEqual(self.bus.inbox("executor"), [])

    def test_claim_unknown_raises(self):
        with self.assertRaises(BusError):
            self.bus.claim("executor", "T404")

    def test_claim_by_wrong_role_raises(self):
        self.bus.submit(make())
        with self.assertRaises(BusError):
            self.bus.claim("verifier", "T1")

    def test_complete(self):
        self.bus.submit(make())
        self.bus.claim("executor", "T1")
        self.bus.complete("executor", "T1")
        self.assertEqual(self.bus.status("T1"), "completed")
        self.assertEqual(self.bus.stats()["completed"], 1)

    def test_reject_returns_to_sender(self):
        self.bus.submit(make(sender="planner", receiver="executor"))
        self.bus.claim("executor", "T1")
        self.bus.reject("executor", "T1", "证据不足")
        self.assertEqual(self.bus.status("T1"), "rejected")
        self.assertEqual([x.id for x in self.bus.inbox("planner")], ["T1"])
        self.assertEqual(self.bus.rejections("T1"), ["证据不足"])

    def test_rejected_can_be_claimed_by_sender(self):
        self.bus.submit(make())
        self.bus.claim("executor", "T1")
        self.bus.reject("executor", "T1", "缺证据")
        self.bus.claim("planner", "T1")
        self.assertEqual(self.bus.status("T1"), "in_progress")

    def test_stats_counts(self):
        self.bus.submit(make(tid="T1"))
        self.bus.submit(make(tid="T2"))
        self.bus.claim("executor", "T1")
        self.bus.complete("executor", "T1")
        self.bus.claim("executor", "T2")
        self.bus.reject("executor", "T2", "不合格")
        stats = self.bus.stats()
        self.assertEqual(stats["submitted"], 2)
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["rejected"], 1)


if __name__ == "__main__":
    unittest.main()