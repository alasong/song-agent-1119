import tempfile
import unittest
from pathlib import Path

from xm.ledger import Ledger
from xm.runner import Agent, Runner


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.led = Ledger(Path(self.tmp.name) / "ledger.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_productive_agent_keeps_dispatching(self):
        runner = Runner(
            self.led, [Agent("alice", "goal/a", productive=True)],
            n_no_progress=2, liveness_enabled=True,
        )
        for _ in range(5):
            runner.tick()
        self.assertEqual(runner.agents[0].status, "active")
        self.assertEqual(runner.readings()["autonomous_dispatch"], 5)

    def test_lazy_agent_downgraded_then_frozen(self):
        runner = Runner(
            self.led, [Agent("bob", "goal/b", productive=False)],
            n_no_progress=2, liveness_enabled=True,
        )
        for _ in range(3):
            runner.tick()
        self.assertEqual(runner.agents[0].status, "readonly")
        self.assertLess(runner.agents[0].budget, 100.0)
        for _ in range(3):
            runner.tick()
        self.assertEqual(runner.agents[0].status, "frozen")

    def test_self_correction_counted(self):
        calls = {"n": 0}

        def verifier(agent, rnd):
            calls["n"] += 1
            return calls["n"] > 1

        runner = Runner(
            self.led, [Agent("carol", "goal/c")],
            n_no_progress=2, liveness_enabled=True, verifier=verifier,
        )
        runner.tick()
        self.assertGreaterEqual(runner.readings()["self_correction"], 1)

    def test_readings_keys(self):
        runner = Runner(self.led, [], liveness_enabled=True)
        self.assertEqual(
            set(runner.readings()),
            {"autonomous_dispatch", "self_correction", "rejection_rate"},
        )


if __name__ == "__main__":
    unittest.main()