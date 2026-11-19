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

    def test_handoff_chain_is_intact(self):
        stats = Scheduler(self.led).run(PLAN)
        self.assertTrue(stats["chain_ok"])
        self.assertEqual(stats["handoffs"], 5)

    def test_broken_worker_breaks_chain(self):
        def bad_worker(role, stage, upstream):
            return {"id": f"{stage}:{role['name']}"}  # 故意丢 upstream

        stats = Scheduler(self.led).run(PLAN, worker=bad_worker)
        self.assertFalse(stats["chain_ok"])

    def test_worker_receives_upstream(self):
        seen = []

        def worker(role, stage, upstream):
            seen.append(upstream["id"] if upstream else None)
            return {"id": f"{stage}:{role['name']}", "upstream": upstream["id"] if upstream else None}

        Scheduler(self.led).run(PLAN, worker=worker)
        self.assertIsNone(seen[0])
        self.assertEqual(seen[1], "拆解:拆解者")

    def test_reject_triggers_one_rework_per_stage(self):
        calls = {"producer": 0}

        def worker(role, stage, upstream):
            if role["kind"] == "verifier":
                return {"id": f"{stage}:v", "upstream": (upstream or {}).get("id"),
                        "verdict": "reject", "reason": "证据不足"}
            calls["producer"] += 1
            return {"id": f"{stage}:{role['name']}:{calls['producer']}",
                    "upstream": (upstream or {}).get("id"), "content": "x"}

        stats = Scheduler(self.led).run(PLAN, worker=worker)
        # 每个阶段：3 个生产/其他角色 + 1 次返工
        self.assertEqual(stats["reworks"], 2)
        self.assertEqual(self.led.count("rework"), 2)

    def test_rework_artifact_feeds_downstream(self):
        order = []

        def worker(role, stage, upstream):
            order.append((stage, role["name"], (upstream or {}).get("id")))
            if role["kind"] == "verifier":
                return {"id": f"{stage}:v", "upstream": (upstream or {}).get("id"),
                        "verdict": "reject", "reason": "再改"}
            return {"id": f"{stage}:{role['name']}:{len(order)}",
                    "upstream": (upstream or {}).get("id"), "content": "x"}

        Scheduler(self.led).run({"process": ["拆解"], "roles": PLAN["roles"]}, worker=worker)
        # 返工产物成为下游（下一阶段/下一角色）的上游
        # 返工由「验证员之前最后一个生产角色」承接，输入是验证裁决
        self.assertIn(("拆解·返工", "实现者", "拆解:v"), order)

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