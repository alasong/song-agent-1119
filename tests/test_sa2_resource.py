"""S8：资源账本 + 采购审批。超阈值进领导队列且不能继续；池不可超支。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sa2.core.ledger import Ledger
from sa2.core.resources import ResourceBook


class ResourceBookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.jsonl"
        self.book = ResourceBook(Ledger(self.path), total=1000, auto_ceiling=100)

    def tearDown(self):
        self.tmp.cleanup()

    def test_auto_spend_within_ceiling(self):
        result = self.book.request(80, "跑一次小实验")
        self.assertEqual(result["status"], "approved")
        self.assertEqual(self.book.spent(), 80)
        self.assertEqual(self.book.remaining(), 920)
        self.assertEqual(self.book.pending(), [])

    def test_over_ceiling_goes_to_leader_and_does_not_spend(self):
        result = self.book.request(500, "买一份数据")
        self.assertEqual(result["status"], "pending")
        self.assertEqual(self.book.spent(), 0, "没批之前一分钱都不许扣")
        self.assertEqual(self.book.remaining(), 1000)
        pending = self.book.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["amount"], 500)

    def test_approve_spends_and_clears_the_queue(self):
        result = self.book.request(500, "买一份数据")
        approved = self.book.approve(result["id"], by="leader")
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(self.book.spent(), 500)
        self.assertEqual(self.book.remaining(), 500)
        self.assertEqual(self.book.pending(), [])

    def test_reject_does_not_spend(self):
        result = self.book.request(500, "买一份数据")
        rejected = self.book.reject(result["id"], by="leader")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(self.book.spent(), 0)
        self.assertEqual(self.book.pending(), [])

    def test_pool_cannot_be_exceeded(self):
        result = self.book.request(2000, "买整库")
        self.assertEqual(result["status"], "refused")
        self.assertEqual(self.book.spent(), 0)

    def test_approve_over_remaining_is_refused(self):
        first = self.book.request(900, "大采购")
        self.book.approve(first["id"], by="leader")
        second = self.book.request(200, "再来一点")
        self.assertEqual(second["status"], "refused", "池里只剩 100，200 的单子不能批也不能排队")

    def test_replay_keeps_the_balance_and_the_pool_is_recorded_once(self):
        self.book.request(80, "小实验")
        pending = self.book.request(500, "买数据")
        replay = ResourceBook(Ledger(self.path), total=999)   # 总额以账本为准，参数不覆盖历史
        self.assertEqual(replay.total(), 1000)
        self.assertEqual(replay.spent(), 80)
        self.assertEqual(replay.remaining(), 920)
        self.assertEqual([x["id"] for x in replay.pending()], [pending["id"]])
        self.assertEqual(replay.ledger.count("resource_pool"), 1)

    def test_unknown_request_is_loud(self):
        with self.assertRaises(KeyError):
            self.book.approve("r-不存在")


if __name__ == "__main__":
    unittest.main()