"""超时的报错要带现场：派单、租约、worker 存活、日志尾。

没有这些，flake 只能靠重跑猜；有了这些，下一次能直接看出卡在哪一步。
"""
import tempfile
import unittest
from pathlib import Path

from sa2.core.ledger import Ledger
from sa2.loop.workers import WorkerPool, _write


class WaitDiagnoseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pool = WorkerPool(self.root, Ledger(self.root / "l.jsonl"), workers=0)

    def tearDown(self):
        self.pool.stop()
        self.tmp.cleanup()

    def test_timeout_carries_dispatch_lease_and_workers(self):
        dispatch_id = "j-diag"
        _write(self.root / "dispatch" / f"{dispatch_id}.json", {"id": dispatch_id})
        _write(self.root / "lease" / f"{dispatch_id}.json",
               {"worker": "w1", "pid": 999999, "expires_at": 1})
        with self.assertRaises(TimeoutError) as caught:
            self.pool.wait(dispatch_id, timeout=0.05)
        message = str(caught.exception)
        self.assertIn("派单存在=True", message)
        self.assertIn("w1", message)
        self.assertIn("worker存活={}", message)

    def test_timeout_carries_log_tail(self):
        (self.root / "worker-w1.log").write_text("a\n最后一行：作业卡住\n", encoding="utf-8")
        with self.assertRaises(TimeoutError) as caught:
            self.pool.wait("j-missing", timeout=0.05)
        self.assertIn("最后一行", str(caught.exception))

    def test_missing_everything_still_says_so(self):
        with self.assertRaises(TimeoutError) as caught:
            self.pool.wait("j-none", timeout=0.05)
        self.assertIn("派单存在=False", str(caught.exception))


if __name__ == "__main__":
    unittest.main()