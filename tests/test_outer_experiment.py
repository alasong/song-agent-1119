"""外环：没有命中就不硬凑候选；没有读数的实验不许采纳；超预算一次都不跑。

`test_sa2_metrics` 只碰过 outer 的落盘路径；这里打 propose 的空手、
active 的容错，以及 run 的三条出口（refused / rejected / adopted）。
"""
import json
import tempfile
import unittest
from pathlib import Path

from sa2.loop import outer


class ProposeTest(unittest.TestCase):
    def test_no_metric_hits_means_no_candidate(self):
        self.assertEqual(outer.propose({}), [])
        self.assertEqual(outer.propose({"validation_pass_rate": 0.5,
                                        "takeover_rate": 0.0,
                                        "communication_efficiency": 0.9}), [])

    def test_rule_fires_with_its_own_baseline(self):
        candidates = outer.propose({"validation_pass_rate": 1.0})
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["metric"], "validation_pass_rate")
        self.assertEqual(candidates[0]["baseline"], 1.0)


class ActiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "notes.jsonl"

    def test_missing_file_reads_empty(self):
        self.assertEqual(outer.active(self.path), [])

    def test_blank_and_corrupt_and_retired_are_skipped(self):
        lines = [
            json.dumps({"id": "a", "status": "active"}, ensure_ascii=False),
            "",
            "{坏行",
            json.dumps({"id": "b", "status": "retired"}, ensure_ascii=False),
        ]
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertEqual([r["id"] for r in outer.active(self.path)], ["a"])


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "experiments.jsonl"
        self.experiment = {"metric": "tokens", "baseline": 100, "expect": "down",
                           "budget": 5_000, "hypothesis": "收紧提示词"}

    def test_over_budget_is_refused_without_running(self):
        calls = []
        record = outer.run({**self.experiment, "budget": 10 ** 6},
                           lambda rec: calls.append(rec) or {"tokens": 1},
                           budget_cap=20_000, path=self.path)
        self.assertEqual(record["status"], "refused")
        self.assertEqual(calls, [], "超预算一次都不许跑")

    def test_missing_reading_is_rejected(self):
        record = outer.run(self.experiment, lambda rec: {}, path=self.path)
        self.assertEqual(record["status"], "rejected")
        self.assertIn("读数", record["why"])

    def test_metric_moving_as_expected_is_adopted(self):
        record = outer.run(self.experiment, lambda rec: {"tokens": 80}, path=self.path)
        self.assertEqual(record["status"], "adopted")
        self.assertEqual(record["after"], 80)
        rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[-1]["status"], "adopted")

    def test_metric_moving_the_wrong_way_is_rejected(self):
        record = outer.run(self.experiment, lambda rec: {"tokens": 120}, path=self.path)
        self.assertEqual(record["status"], "rejected")


if __name__ == "__main__":
    unittest.main()