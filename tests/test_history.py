"""跨轮记录与增长读数：没有质量分就不许说「能力增长」。"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from xm import history


def rec(ts: str, quality: int | None, calls: int = 3, family: str = "rsi",
        passed: bool = True, mode: str = "single") -> history.Record:
    return history.Record(ts=ts, family=family, goal="目标", org_signature="none/stages0",
                          mode=mode, passed=passed, quality=quality, calls=calls,
                          prompt_tokens=100, completion_tokens=50, chars=3000,
                          artifact="/tmp/x.md")


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "history.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_and_load_roundtrip(self):
        history.append(rec("2026-01-01T00:00:00", 7), self.path)
        history.append(rec("2026-01-02T00:00:00", 9), self.path)
        rows, bad = history.load(self.path)
        self.assertEqual([r.quality for r in rows], [7, 9])
        self.assertEqual(bad, 0)

    def test_bad_lines_are_counted_not_swallowed(self):
        self.path.write_text('{"ts": "x"}\n不是JSON\n', encoding="utf-8")
        rows, bad = history.load(self.path)
        self.assertEqual(rows, [])
        self.assertEqual(bad, 2, "坏行必须报出来，不能静默丢")

    def test_signature_distinguishes_different_orgs(self):
        a = history.signature([{"kind": "planner"}, {"kind": "verifier"}], 2)
        b = history.signature([{"kind": "planner"}], 2)
        self.assertNotEqual(a, b, "两套班子必须有不同签名，否则没法比")

    def test_signature_counts_names_when_kind_missing(self):
        self.assertEqual(history.signature(["甲", "乙", "丙"], 3), "3roles/stages3")


class GrowthTest(unittest.TestCase):
    def test_single_run_cannot_claim_growth(self):
        table = history.growth([rec("2026-01-01T00:00:00", 7)])
        self.assertFalse(table["rsi"]["can_claim_growth"])

    def test_two_scored_runs_can_claim_growth(self):
        table = history.growth([rec("2026-01-01T00:00:00", 7), rec("2026-01-02T00:00:00", 9)])
        self.assertTrue(table["rsi"]["can_claim_growth"])
        self.assertFalse(table["rsi"]["regressed"])

    def test_regression_is_flagged(self):
        table = history.growth([rec("2026-01-01T00:00:00", 9), rec("2026-01-02T00:00:00", 5)])
        self.assertTrue(table["rsi"]["regressed"], "这轮比历史上最好那次差，必须算退化")

    def test_unscored_runs_can_not_claim_growth(self):
        table = history.growth([rec("2026-01-01T00:00:00", None), rec("2026-01-02T00:00:00", None)])
        self.assertFalse(table["rsi"]["can_claim_growth"], "只有成本没有质量分，只能算效率")


class GrowthScriptTest(unittest.TestCase):
    def run_script(self, rows: list[history.Record]) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.jsonl"
            for r in rows:
                history.append(r, path)
            proc = subprocess.run([sys.executable, "scripts/growth.py", "--history", str(path)],
                                  cwd=ROOT, capture_output=True, text=True)
            return proc.returncode, proc.stdout

    def test_exit_code_red_without_scored_history(self):
        rc, out = self.run_script([rec("2026-01-01T00:00:00", None)])
        self.assertEqual(rc, 1, out)

    def test_exit_code_green_with_two_improving_runs(self):
        rc, out = self.run_script([rec("2026-01-01T00:00:00", 7), rec("2026-01-02T00:00:00", 9)])
        self.assertEqual(rc, 0, out)
        self.assertIn("能声称增长", out)


if __name__ == "__main__":
    unittest.main()