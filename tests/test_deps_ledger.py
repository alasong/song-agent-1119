"""W5：断言单通过后进账本；被拒时记 preflight_reject 且带阶段。"""
import tempfile
import unittest
from pathlib import Path

from tests.deps_fixture import Fixture, note


class DepLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _claims(self, ledger):
        return [e for e in ledger.read() if e["kind"] == "dependency_claim"]

    def test_each_accepted_note_is_recorded(self):
        notes = {stage: note(stage) for stage in ("起草", "成稿")}
        fx = Fixture(self.root, require_deps=True, dep_notes=notes)
        self.assertTrue(fx.pdca.run(fx.decl())["passed"])
        claims = self._claims(fx.ledger)
        self.assertEqual(len(claims), 2, claims)
        payload = claims[0]["payload"]
        for key in ("stage", "name", "cls", "claim", "verify"):
            self.assertIn(key, payload)
        self.assertEqual({e["payload"]["stage"] for e in claims}, {"起草", "成稿"})

    def test_missing_note_reject_is_recorded_with_stage(self):
        fx = Fixture(self.root, require_deps=True)
        fx.pdca.run(fx.decl())
        rejects = [e for e in fx.ledger.read() if e["kind"] == "preflight_reject"]
        self.assertEqual(len(rejects), 1, rejects)
        self.assertEqual(rejects[0]["payload"]["stage"], "起草")
        self.assertTrue(rejects[0]["payload"]["problems"])

    def test_no_note_no_claim(self):
        fx = Fixture(self.root)
        fx.pdca.run(fx.decl())
        self.assertEqual(self._claims(fx.ledger), [])


if __name__ == "__main__":
    unittest.main()