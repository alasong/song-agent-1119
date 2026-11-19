"""常驻循环测试：不睡觉，靠 max_ticks 收敛。"""
import tempfile
import unittest
from pathlib import Path

from xm.ledger import Ledger
from xm.resident import Resident, ResidentConfig


def policy(state):
    done = state.get("done", [])
    if "audit" not in done:
        return "audit", lambda: {"progress": True, "note": "第一轮自检"}
    if "diagnose" not in done:
        return "diagnose", lambda: {"progress": True, "note": "第二轮诊断"}
    return "idle", lambda: {"progress": False}


class ResidentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.led = Ledger(Path(self.tmp.name) / "l.jsonl")
        self.cp = Path(self.tmp.name) / "checkpoint.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_policy_drives_task_choice(self):
        r = Resident(self.led, policy, ResidentConfig(interval_s=0, max_hours=1, max_ticks=3,
                                                      checkpoint=self.cp))
        summary = r.run()
        self.assertEqual(summary["ticks"], 3)
        self.assertEqual(summary["tasks"], ["audit", "diagnose", "idle"])
        self.assertEqual(summary["distinct_tasks"], 3)
        self.assertEqual(summary["progress_tasks"], 2)

    def test_checkpoint_written(self):
        r = Resident(self.led, policy, ResidentConfig(interval_s=0, max_hours=1, max_ticks=1,
                                                      checkpoint=self.cp))
        r.run()
        data = __import__("json").loads(self.cp.read_text(encoding="utf-8"))
        self.assertEqual(data["ticks"], 1)
        self.assertEqual(data["last"]["task"], "audit")

    def test_failed_task_recorded_not_hidden(self):
        def boom():
            raise RuntimeError("坏了")

        r = Resident(self.led, lambda s: ("broken", boom),
                     ResidentConfig(interval_s=0, max_hours=1, max_ticks=1))
        summary = r.run()
        self.assertEqual(summary["progress_tasks"], 0)
        self.assertIn("RuntimeError", r.history[0]["result"]["error"])

    def test_resume_counts_already_elapsed(self):
        clock = {"t": 0.0}
        r = Resident(self.led, policy, ResidentConfig(interval_s=0, max_hours=1, max_ticks=1,
                                                      already_elapsed_h=0.5))
        summary = r.run()
        self.assertGreaterEqual(summary["hours"], 0.5)

    def test_full_elapsed_means_no_waiting(self):
        r = Resident(self.led, policy, ResidentConfig(max_hours=1, already_elapsed_h=1.0))
        summary = r.run()
        self.assertEqual(summary["ticks"], 0)
        self.assertGreaterEqual(summary["hours"], 1.0)

    def test_runs_full_window_not_early_exit(self):
        """回归测试：循环不能因为「下一次 sleep 越过 deadline」就提前收工。"""
        r = Resident(self.led, policy,
                     ResidentConfig(interval_s=0.05, max_hours=0.00028))  # ~1 秒
        summary = r.run()
        self.assertGreaterEqual(summary["hours"], 0.00028, "提前退出了，24h 判据会永远判不过")

    def test_max_hours_respected(self):
        r = Resident(self.led, policy, ResidentConfig(interval_s=1, max_hours=0.0001))
        summary = r.run()
        self.assertLess(summary["ticks"], 10)


if __name__ == "__main__":
    unittest.main()