"""M1 判据：端到端装配（非法工单必须被拒收）。

这条判据由人写（第一圈必须有人给起点）；实现由系统在 sandbox/ 里完成，
产出 diff 交人审后才合入项目。
"""
import unittest
from pathlib import Path

# 实现未合入项目前跳过；合入后会自动开始跑（判据先于实现，但不阻塞主干）
HAS_IMPL = Path("xm/app.py").exists()

if HAS_IMPL:
    from xm.app import Org
    from xm.ticket import TicketError


@unittest.skipUnless(HAS_IMPL, "xm/app.py 尚未合入（实现由系统在 sandbox/ 里产出，待审）")
class M1OrgTest(unittest.TestCase):
    def setUp(self):
        self.org = Org()

    def test_submit_creates_task_ticket(self):
        tid = self.org.submit("做一个 A 实验")
        self.assertEqual(self.org.bus.status(tid), "submitted")
        self.assertEqual(self.org.bus.stats()["submitted"], 1)

    def test_invalid_ticket_rejected_not_silently_accepted(self):
        with self.assertRaises(TicketError):
            self.org.submit_raw({"id": "X1"})  # 缺必填字段
        self.assertEqual(self.org.bus.stats()["submitted"], 0)

    def test_tick_rejects_when_gates_not_met(self):
        tid = self.org.submit("做个 B")
        self.org.tick()
        self.assertEqual(self.org.bus.status(tid), "rejected")

    def test_metrics_snapshot_has_five_indicators(self):
        self.assertEqual(len(self.org.metrics.snapshot()), 5)

    def test_reports_lists_rejected_ids(self):
        tid = self.org.submit("做个 C")
        self.org.tick()
        self.assertIn(tid, self.org.reports())


if __name__ == "__main__":
    unittest.main()