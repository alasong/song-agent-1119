"""W11：依赖三读数——覆盖率、断言命中率、缺口发现率，只从账本能算的量里取。"""
import tempfile
import unittest
from pathlib import Path

from sa2.core import metrics
from tests.deps_fixture import Fixture, note


def ev(kind, actor="loop", payload=None):
    return {"kind": kind, "actor": actor, "payload": payload or {}}


class DepMetricsTest(unittest.TestCase):
    def test_three_readings(self):
        events = [
            ev("stage_ok", "起草", {"attempt": 1}),
            ev("stage_ok", "成稿", {"attempt": 1}),
            ev("dependency_claim", "deps", {"stage": "起草", "name": "a"}),
            ev("dependency_claim", "deps", {"stage": "成稿", "name": "b"}),
            ev("claim_verified", "deps", {"stage": "起草", "name": "a"}),
            ev("claim_missed", "deps", {"stage": "成稿", "name": "b"}),
        ]
        out = metrics.compute(events)
        self.assertEqual(out["dep_coverage"], 1.0)
        self.assertEqual(out["claim_hit_rate"], 0.5)
        self.assertEqual(out["dep_gap_rate"], 0.5)
        self.assertTrue(any("缺口发现率" in f for f in out["flags"]), out["flags"])

    def test_stage_without_note_is_flagged(self):
        out = metrics.compute([ev("stage_ok", "起草", {"attempt": 1})])
        self.assertEqual(out["dep_coverage"], 0.0)
        self.assertTrue(any("没写依赖断言" in f for f in out["flags"]), out["flags"])

    def test_no_claims_means_no_gap_rate(self):
        out = metrics.compute([ev("stage_ok", "起草", {"attempt": 1})])
        self.assertIsNone(out["dep_gap_rate"])
        self.assertIsNone(out["claim_hit_rate"])

    def test_blocked_run_has_no_coverage(self):
        out = metrics.compute([ev("preflight_reject", "gate", {"problems": ["x"]})])
        self.assertIsNone(out["dep_coverage"])

    def test_from_real_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp, require_deps=True,
                         dep_notes={s: note(s) for s in ("起草", "成稿")})
            self.assertTrue(fx.pdca.run(fx.decl())["passed"])
            out = metrics.compute(fx.ledger.read())
            self.assertEqual(out["dep_coverage"], 1.0)
            self.assertEqual(out["dep_gap_rate"], 0.0)
            self.assertIsNone(out["claim_hit_rate"])   # 这一轮没有验证动作


if __name__ == "__main__":
    unittest.main()