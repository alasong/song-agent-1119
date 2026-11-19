"""产物边界守卫：任务产物不得写进项目正文（docs/ xm/ tests/ scripts/）。"""
import unittest

from xm.daemon import DaemonConfig


class IsolationTest(unittest.TestCase):
    def _cfg(self, target):
        return DaemonConfig(spec="s", target_file=target, tests=["tests.test_gates"])

    def test_runs_is_allowed(self):
        cfg = self._cfg("runs/x/report.md")
        self.assertEqual(cfg.target_file, "runs/x/report.md")

    def test_docs_target_rejected(self):
        with self.assertRaises(ValueError):
            self._cfg("docs/ai-money.md")

    def test_code_target_rejected(self):
        with self.assertRaises(ValueError):
            self._cfg("xm/retry.py")

    def test_test_target_rejected(self):
        with self.assertRaises(ValueError):
            self._cfg("tests/test_x.py")

    def test_project_root_file_rejected(self):
        with self.assertRaises(ValueError):
            self._cfg("README.md")


if __name__ == "__main__":
    unittest.main()