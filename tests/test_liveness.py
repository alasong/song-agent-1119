"""反例测试：关掉无进展检测后，这条必须变红。

验证方式（ROADMAP §1 M0a）：
    XM_DISABLE_LIVENESS=1 python3 -m unittest discover -s tests -t . -p 'test_liveness.py'
应当失败（exit != 0）。
"""
import tempfile
import unittest
from pathlib import Path

from xm.ledger import Ledger
from xm.runner import Agent, Runner


class LivenessReverseTest(unittest.TestCase):
    def test_idle_agent_must_be_frozen(self):
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(Path(d) / "ledger.jsonl")
            runner = Runner(led, [Agent("idle", "goal/z", productive=False)], n_no_progress=2)
            for _ in range(2 * 2 + 2):
                runner.tick()
            self.assertEqual(runner.agents[0].status, "frozen")


if __name__ == "__main__":
    unittest.main()