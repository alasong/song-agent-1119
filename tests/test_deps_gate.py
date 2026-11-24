"""W4：step（阶段）级输入门——没断言单或断言不可验，本步零调用。"""
import tempfile
import unittest
from pathlib import Path

from tests.deps_fixture import Fixture, note


class DepGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_note_blocks_before_any_call(self):
        fx = Fixture(self.root, require_deps=True)
        report = fx.pdca.run(fx.decl())
        self.assertFalse(report["passed"])
        self.assertEqual(fx.calls, [])
        self.assertEqual(report["dispatches"], 0)
        self.assertTrue(any("没有提交依赖断言单" in p for p in report["problems"]),
                        report["problems"])

    def test_bad_verify_blocks(self):
        notes = {"起草": note("起草", "跑一下看看"), "成稿": note("成稿")}
        fx = Fixture(self.root, require_deps=True, dep_notes=notes)
        report = fx.pdca.run(fx.decl())
        self.assertFalse(report["passed"])
        self.assertEqual(fx.calls, [])

    def test_valid_notes_pass(self):
        notes = {stage: note(stage) for stage in ("起草", "成稿")}
        fx = Fixture(self.root, require_deps=True, dep_notes=notes)
        report = fx.pdca.run(fx.decl())
        self.assertTrue(report["passed"], report)
        self.assertGreater(len(fx.calls), 0)

    def test_second_stage_blocked_when_its_note_missing(self):
        fx = Fixture(self.root, require_deps=True, dep_notes={"起草": note("起草")})
        report = fx.pdca.run(fx.decl())
        self.assertFalse(report["passed"])
        self.assertTrue(any("成稿" in p for p in report["problems"]), report["problems"])
        self.assertTrue(all(stage == "起草" for _, stage, _ in fx.calls), fx.calls)

    def test_gate_off_keeps_old_behaviour(self):
        fx = Fixture(self.root)
        report = fx.pdca.run(fx.decl())
        self.assertTrue(report["passed"], report)


if __name__ == "__main__":
    unittest.main()