"""判据运行时验收（G3 的机检基础）。"""
import sys
import tempfile
import unittest
from pathlib import Path

from xm.criteria_runtime import OWNER, CriteriaError, CriteriaRuntime


class CriteriaRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "criteria.jsonl"
        self.rt = CriteriaRuntime(self.path, writer=OWNER)

    def tearDown(self):
        self.tmp.cleanup()

    def test_generator_cannot_register(self):
        gen = CriteriaRuntime(writer="generator")
        with self.assertRaises(CriteriaError):
            gen.register("x", "regex", {"pattern": "ok"})

    def test_regex_criterion(self):
        self.rt.register("含 OK", "regex", {"pattern": r"\bOK\b"})
        self.assertTrue(self.rt.check("含 OK", {"text": "结果 OK"})["ok"])
        self.assertFalse(self.rt.check("含 OK", {"text": "结果 NG"})["ok"])

    def test_exec_criterion(self):
        self.rt.register("退码为零", "exec", {"cmd": [sys.executable, "-c", "pass"]})
        self.assertTrue(self.rt.check("退码为零")["ok"])
        self.rt.register("必然失败", "exec", {"cmd": [sys.executable, "-c", "raise SystemExit(3)"]})
        self.assertFalse(self.rt.check("必然失败")["ok"])

    def test_callable_criterion(self):
        self.rt.register("长度够", "callable", {"target": "builtins:bool"})
        self.assertTrue(self.rt.check("长度够", {"x": 1})["ok"])

    def test_revise_bumps_version_and_needs_owner(self):
        self.rt.register("可复现", "regex", {"pattern": "a"})
        crit = self.rt.revise("可复现", {"pattern": "b"})
        self.assertEqual(crit.version, 2)
        gen = CriteriaRuntime(self.path, writer="generator")
        with self.assertRaises(CriteriaError):
            gen.revise("可复现", {"pattern": "c"})

    def test_persisted_across_instances(self):
        self.rt.register("持久判据", "regex", {"pattern": "z"})
        again = CriteriaRuntime(self.path, writer=OWNER)
        self.assertEqual(again.get("持久判据").kind, "regex")

    def test_digest_changes_on_revise(self):
        self.rt.register("d", "regex", {"pattern": "a"})
        before = self.rt.digest("d")
        self.rt.revise("d", {"pattern": "b"})
        self.assertNotEqual(before, self.rt.digest("d"))

    def test_broken_criterion_reports_not_passes(self):
        self.rt.register("坏的", "callable", {"target": "no_such_module:fn"})
        result = self.rt.check("坏的", {})
        self.assertFalse(result["ok"])
        self.assertIn("Error", result["detail"])


if __name__ == "__main__":
    unittest.main()