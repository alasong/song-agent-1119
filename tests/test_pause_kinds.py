"""W7：暂停分两种来源——越界自动停，外部随时停；都能从检查点恢复。"""
import tempfile
import unittest
from pathlib import Path

from tests.deps_fixture import Fixture


class PauseKindsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def kinds(self, fixture):
        return [e["kind"] for e in fixture.ledger.read()]

    def test_budget_stop_is_pause_auto(self):
        fx = Fixture(self.root, produce=lambda *a, **k: "x" * 400)
        report = fx.pdca.run(fx.decl(budget_tokens=50))
        self.assertFalse(report["passed"])
        self.assertIn("预算用尽", report["reason"])
        self.assertIn("pause_auto", self.kinds(fx))
        self.assertNotIn("budget_stop", self.kinds(fx))

    def test_external_stop_between_stages(self):
        ticks = {"n": 0}

        def stop():
            ticks["n"] += 1
            return ticks["n"] >= 2

        fx = Fixture(self.root, stop_requested=stop)
        report = fx.pdca.run(fx.decl())
        self.assertFalse(report["passed"])
        self.assertIn("外部叫停", report["reason"])
        self.assertIn("pause_external", self.kinds(fx))
        self.assertTrue(all(stage == "起草" for _, stage, _ in fx.calls), fx.calls)

    def test_resume_after_external_stop_skips_finished_stage(self):
        state_path = self.root / "state.json"
        ticks = {"n": 0}

        def stop():
            ticks["n"] += 1
            return ticks["n"] >= 2

        first = Fixture(self.root, stop_requested=stop, state_path=state_path)
        first.pdca.run(first.decl())
        self.assertTrue(state_path.exists())

        second = Fixture(self.root, resume=True, state_path=state_path)
        report = second.pdca.run(second.decl())
        self.assertTrue(report["passed"], report)
        self.assertTrue(second.calls, "恢复后至少该派一次活")
        self.assertTrue(all(stage == "成稿" for _, stage, _ in second.calls), second.calls)


if __name__ == "__main__":
    unittest.main()