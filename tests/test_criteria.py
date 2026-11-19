import unittest

from xm.criteria import CriterionError, Registry


class CriteriaTest(unittest.TestCase):
    def setUp(self):
        self.reg = Registry()

    def test_register_and_get(self):
        self.reg.register("可复现", 1, lambda case: case["ran"])
        entry = self.reg.get("可复现")
        self.assertEqual(entry["version"], 1)
        self.assertTrue(entry["judge"]({"ran": True}))

    def test_uncalibrated_proposal_rejected(self):
        self.reg.register("可复现", 1, lambda c: True)
        ok = self.reg.propose(
            "可复现", 2, lambda c: True, calibration=lambda old, new: False
        )
        self.assertFalse(ok)
        self.assertEqual(self.reg.get("可复现")["version"], 1)

    def test_calibrated_proposal_promoted(self):
        self.reg.register("可复现", 1, lambda c: True)
        ok = self.reg.propose(
            "可复现", 2, lambda c: False, calibration=lambda old, new: True
        )
        self.assertTrue(ok)
        self.assertEqual(self.reg.get("可复现")["version"], 2)

    def test_unknown_criterion_raises(self):
        with self.assertRaises(CriterionError):
            self.reg.get("不存在的判据")


if __name__ == "__main__":
    unittest.main()