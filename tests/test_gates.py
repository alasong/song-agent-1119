import unittest

from xm.gates import REQUIRED, STAGES, GateChain, GateFailed


class GateTest(unittest.TestCase):
    def _run_all(self, skip=None):
        chain = GateChain()
        for stage in STAGES:
            if stage == skip:
                continue
            chain.check(stage, {REQUIRED[stage]: True})
        return chain

    def test_in_order_passes(self):
        chain = self._run_all()
        self.assertEqual(chain.passed, STAGES)

    def test_skipping_a_stage_raises(self):
        with self.assertRaises(GateFailed):
            self._run_all(skip="设计")

    def test_missing_artifact_raises(self):
        with self.assertRaises(GateFailed):
            GateChain().check("需求分解", {})

    def test_unknown_stage_raises(self):
        with self.assertRaises(GateFailed):
            GateChain().check("拍脑袋", {})


if __name__ == "__main__":
    unittest.main()