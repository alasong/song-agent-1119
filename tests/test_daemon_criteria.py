"""判据运行时接进 daemon 验收路径的验收（补 G3 的「通电」）。"""
import sys
import tempfile
import unittest
from pathlib import Path

from xm.criteria_runtime import OWNER, CriteriaRuntime
from xm.daemon import Daemon, DaemonConfig
from xm.ledger import Ledger


class DaemonCriteriaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runs = self.root / "runs"
        self.runs.mkdir()
        self.led = Ledger(self.root / "l.jsonl")
        self.crit_path = self.root / "criteria.jsonl"
        owner = CriteriaRuntime(self.crit_path, writer=OWNER)
        owner.register("含通过字样", "regex", {"pattern": "通过"})

    def tearDown(self):
        self.tmp.cleanup()

    def _cfg(self, **over):
        base = dict(
            spec="写一个文档",
            target_file=str(self.runs / "doc.md"),
            tests=[],
            artifacts_root=str(self.runs),
            criteria=["含通过字样"],
            criteria_path=str(self.crit_path),
            max_rounds=1,
        )
        base.update(over)
        return DaemonConfig(**base)

    def test_criteria_pass_makes_round_green(self):
        out = "```markdown\n本方案通过验收\n```"
        daemon = Daemon(self.led, lambda m: out, self._cfg())
        summary = daemon.run()
        self.assertEqual(summary["green_at_round"], 1)
        self.assertEqual(summary["final_rc"], 0)

    def test_criteria_fail_keeps_red(self):
        out = "```markdown\n本方案不合格\n```"
        daemon = Daemon(self.led, lambda m: out, self._cfg())
        summary = daemon.run()
        self.assertIsNone(summary["green_at_round"])
        self.assertEqual(summary["final_rc"], 1)

    def test_daemon_cannot_register_criteria(self):
        out = "```markdown\n随便\n```"
        daemon = Daemon(self.led, lambda m: out, self._cfg(criteria=["不存在的判据"]))
        summary = daemon.run()
        self.assertEqual(summary["final_rc"], 1)  # 未注册判据 → 判红，而不是默认通过


if __name__ == "__main__":
    unittest.main()