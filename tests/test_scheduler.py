"""调度器验收：编制方案必须真的被派出去。"""
import tempfile
import unittest
from pathlib import Path

from xm.ledger import Ledger
from xm.scheduler import Scheduler

PLAN = {
    "goal": "跑通一单",
    "process": ["拆解", "实现"],
    "roles": [
        {"name": "拆解者", "kind": "planner", "duty": "d", "criteria": "c", "budget": 1000},
        {"name": "实现者", "kind": "executor", "duty": "d", "criteria": "c", "budget": 1000},
        {"name": "复核者", "kind": "verifier", "duty": "d", "criteria": "c", "budget": 1000},
    ],
}


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.led = Ledger(Path(self.tmp.name) / "l.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_dispatches_every_role_each_stage(self):
        stats = Scheduler(self.led).run(PLAN)
        self.assertEqual(stats["stages"], 2)
        self.assertEqual(stats["dispatches"], 6)
        self.assertEqual(stats["distinct_roles"], 3)
        self.assertTrue(stats["has_verifier"])

    def test_ledger_records_dispatch_and_progress(self):
        Scheduler(self.led).run(PLAN)
        self.assertEqual(self.led.count("dispatch"), 6)
        self.assertEqual(self.led.count("progress"), 6)

    def test_missing_plan_raises(self):
        with self.assertRaises(ValueError):
            Scheduler(self.led).run({"roles": [], "process": []})

    def test_from_plan_file(self):
        path = Path(self.tmp.name) / "plan.json"
        path.write_text(__import__("json").dumps(PLAN, ensure_ascii=False), encoding="utf-8")
        stats = Scheduler.from_plan_file(path, self.led).run()
        self.assertEqual(stats["dispatched" if False else "dispatches"], 6)


if __name__ == "__main__":
    unittest.main()