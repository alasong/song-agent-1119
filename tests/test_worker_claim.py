"""租约抢占的三条条件：坏文件、持有者已死、已过期。

flaky 的候选根因：租约文件读不出来时原实现返回 None，作业永远没人领，
表现就是 wait() 一直等到超时。
"""
import os
import tempfile
import unittest
from pathlib import Path

from sa2.loop.workers import _claim, _read, _write


class ClaimTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lease = Path(self.tmp.name) / "lease" / "j-1.json"
        self.lease.parent.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_claim_creates_lease(self):
        self.assertEqual(_claim(self.lease, "w1", os.getpid(), ttl=1.0), {})
        self.assertEqual(_read(self.lease)["worker"], "w1")

    def test_live_holder_is_not_stolen(self):
        _write(self.lease, {"worker": "w1", "pid": os.getpid(),
                            "expires_at": 10 ** 12})
        self.assertIsNone(_claim(self.lease, "w2", os.getpid(), ttl=1.0))

    def test_expired_lease_is_taken_over(self):
        old = {"worker": "w1", "pid": os.getpid(), "expires_at": 1}
        _write(self.lease, old)
        self.assertEqual(_claim(self.lease, "w2", os.getpid(), ttl=1.0)["worker"], "w1")
        self.assertEqual(_read(self.lease)["worker"], "w2")

    def test_dead_holder_is_taken_over_before_expiry(self):
        old = {"worker": "w1", "pid": 999999, "expires_at": 10 ** 12}
        _write(self.lease, old)
        self.assertEqual(_claim(self.lease, "w2", os.getpid(), ttl=1.0)["worker"], "w1")

    def test_corrupt_lease_waits_for_grace_then_recovers(self):
        self.lease.write_text("", encoding="utf-8")
        # 刚建的空文件还在 ttl 宽限内：可能是别的 worker 正在写，不抢
        self.assertIsNone(_claim(self.lease, "w2", os.getpid(), ttl=1.0))
        # 超过宽限还坏着：按坏租约抢占，否则作业永远没人领
        os.utime(self.lease, (0, 0))
        self.assertEqual(_claim(self.lease, "w1", os.getpid(), ttl=1.0), {})
        self.assertEqual(_read(self.lease)["worker"], "w1")


if __name__ == "__main__":
    unittest.main()