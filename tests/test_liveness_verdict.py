"""G1 验收路径测试：报告到了会不会判绿、字段读错会不会被发现。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.bench import liveness_ok


class LivenessVerdictTest(unittest.TestCase):
    def test_full_run_passes(self):
        self.assertTrue(liveness_ok(24.0, 12, 4))

    def test_short_run_fails(self):
        self.assertFalse(liveness_ok(23.9, 12, 4))

    def test_too_few_progress_tasks_fails(self):
        self.assertFalse(liveness_ok(24.0, 9, 4))

    def test_too_few_task_kinds_fails(self):
        self.assertFalse(liveness_ok(24.0, 12, 2))

    def test_zero_everything_fails(self):
        self.assertFalse(liveness_ok(0, 0, 0))


if __name__ == "__main__":
    unittest.main()