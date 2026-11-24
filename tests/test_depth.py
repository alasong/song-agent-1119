"""W9：go 的默认深度上限是 3 层，第 4 层起必须人确认。"""
import unittest

from sa2.core import deps


class DepthTest(unittest.TestCase):
    def test_three_layers_pass(self):
        self.assertTrue(deps.depth_ok(3)["ok"])

    def test_fourth_layer_needs_a_human(self):
        result = deps.depth_ok(4)
        self.assertFalse(result["ok"])
        self.assertIn("人确认", result["why"])
        self.assertEqual(result["limit"], 3)

    def test_limit_comes_from_thresholds(self):
        self.assertEqual(deps.depth_ok(3)["limit"], 3)
        self.assertEqual(deps.depth_ok(99)["limit"], 3)


if __name__ == "__main__":
    unittest.main()