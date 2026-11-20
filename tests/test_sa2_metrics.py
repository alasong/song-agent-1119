"""S7：健康指标 + 外环。指标必须能从历史 run 复算；外环的候选必须有预算上限与落盘决定。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sa2.core.metrics import compute, from_run
from sa2.loop.outer import propose, run


def events():
    return [
        {"kind": "dispatch", "payload": {"chars": 10}},
        {"kind": "reject", "payload": {}},
        {"kind": "stage_ok", "payload": {}},
        {"kind": "dispatch", "payload": {"chars": 0}},
        {"kind": "takeover", "payload": {}},
        {"kind": "delivery", "payload": {"passed": True}},
    ]


class MetricsTest(unittest.TestCase):
    def test_rates_come_from_the_ledger(self):
        m = compute(events(), {"chars": 500, "budget": {"spent": 1000}})
        self.assertAlmostEqual(m["validation_pass_rate"], 0.5)      # 1 ok / (1 ok + 1 reject)
        self.assertAlmostEqual(m["takeover_rate"], 0.5)             # 1 / 2 dispatches
        self.assertAlmostEqual(m["resource_efficiency"], 500.0)
        self.assertAlmostEqual(m["communication_efficiency"], 0.5)  # 1 of 2 有产出
        self.assertTrue(m["delivery_passed"])

    def test_empty_is_null_not_zero(self):
        m = compute([], None)
        self.assertIsNone(m["validation_pass_rate"])
        self.assertIsNone(m["takeover_rate"])
        self.assertIsNone(m["resource_efficiency"])
        self.assertIsNone(m["communication_efficiency"])
        self.assertIn("目标偏离度", "；".join(m["unavailable"]))

    def test_high_pass_rate_is_flagged_not_congratulated(self):
        m = compute([{"kind": "stage_ok", "payload": {}},
                     {"kind": "stage_ok", "payload": {}}], {})
        self.assertIn("校验通过率过高", "；".join(m["flags"]))

    def test_from_run_replays_a_saved_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = "\n".join(json.dumps(e, ensure_ascii=False) for e in events())
            (root / "ledger.jsonl").write_text(ledger + "\n", encoding="utf-8")
            (root / "readings.json").write_text(
                json.dumps({"chars": 200, "budget": {"spent": 400}}), encoding="utf-8")
            m = from_run(root)
            self.assertAlmostEqual(m["resource_efficiency"], 500.0)
            self.assertAlmostEqual(m["validation_pass_rate"], 0.5)


class OuterTest(unittest.TestCase):
    def test_proposes_when_pass_rate_is_suspicious(self):
        got = propose({"validation_pass_rate": 0.99, "takeover_rate": 0.0,
                       "communication_efficiency": 1.0})
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["metric"], "validation_pass_rate")
        self.assertEqual(got[0]["expect"], "down")

    def test_no_proposal_when_healthy(self):
        self.assertEqual(propose({"validation_pass_rate": 0.7, "takeover_rate": 0.0,
                                  "communication_efficiency": 0.9}), [])

    def test_over_budget_is_refused_without_running(self):
        calls: list[int] = []
        experiment = {"hypothesis": "x", "metric": "validation_pass_rate",
                      "baseline": 0.99, "expect": "down", "budget": 999_999}
        record = run(experiment, lambda e: calls.append(1) or {"validation_pass_rate": 0.5},
                     budget_cap=1000)
        self.assertEqual(record["status"], "refused")
        self.assertEqual(calls, [], "超预算的实验一次都不许跑")

    def test_adopt_and_reject_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outer.jsonl"
            experiment = {"hypothesis": "加一条反例判据", "metric": "validation_pass_rate",
                          "baseline": 0.99, "expect": "down", "budget": 500}
            adopted = run(experiment, lambda e: {"validation_pass_rate": 0.5},
                          budget_cap=1000, path=path)
            self.assertEqual(adopted["status"], "adopted")
            rejected = run(experiment, lambda e: {"validation_pass_rate": 0.995},
                           budget_cap=1000, path=path)
            self.assertEqual(rejected["status"], "rejected")
            lines = [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
            self.assertEqual(len(lines), 2, "两次实验决定都要落盘")
            self.assertEqual(json.loads(lines[0])["status"], "adopted")


if __name__ == "__main__":
    unittest.main()