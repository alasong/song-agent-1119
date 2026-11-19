"""成本止损验收：预算超了必须停，并且记账。"""
import sys
import tempfile
import unittest
from pathlib import Path

from xm.daemon import Daemon, DaemonConfig
from xm.ledger import Ledger


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.led = Ledger(self.root / "l.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def _cfg(self, budget):
        return DaemonConfig(
            spec="写点东西",
            target_file=str(self.root / "runs" / "x.md"),
            tests=[],
            artifacts_root=str(self.root / "runs"),
            verify_cmd=[sys.executable, "-c", "pass"],
            max_rounds=5,
            budget_tokens=budget,
        )

    def test_stops_when_budget_exceeded(self):
        big = "```markdown\n" + ("x" * 2000) + "\n```"
        daemon = Daemon(self.led, lambda m: big, self._cfg(10))
        summary = daemon.run()
        self.assertTrue(summary["stopped_by_budget"])
        self.assertEqual(summary["budget_tokens"], 10)
        self.assertGreater(summary["spent_tokens"], 10)
        self.assertEqual(self.led.count("budget_stop"), 1)

    def test_no_budget_means_no_stop(self):
        ok = "```markdown\nok\n```"
        daemon = Daemon(self.led, lambda m: ok, self._cfg(None))
        summary = daemon.run()
        self.assertFalse(summary["stopped_by_budget"])
        self.assertIsNone(summary["budget_tokens"])


if __name__ == "__main__":
    unittest.main()