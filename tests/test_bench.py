"""判据工具自身的回归测试：bench 不许静默失效。"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {"G1 自主性", "G2 组织性", "G3 判据能力", "G4 知识扩展", "G5 不漂移", "G6 成本可控"}


class BenchSelfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        proc = subprocess.run([sys.executable, "scripts/bench.py", "--json"],
                              cwd=ROOT, capture_output=True, text=True)
        cls.rc = proc.returncode
        cls.report = json.loads(proc.stdout)

    def test_all_six_checks_present(self):
        ids = {c["id"] for c in self.report["checks"]}
        self.assertEqual(ids, EXPECTED)

    def test_every_check_has_evidence_and_next_step(self):
        for check in self.report["checks"]:
            self.assertTrue(check["evidence"], f"{check['id']} 缺 evidence")
            if not check["passed"]:
                self.assertTrue(check["next"], f"{check['id']} 红了却没有最小下一步")

    def test_verdict_matches_exit_code(self):
        all_passed = all(c["passed"] for c in self.report["checks"])
        self.assertEqual(self.report["passed"], sum(c["passed"] for c in self.report["checks"]))
        self.assertEqual(self.report["verdict"], "够了" if all_passed else "不够")
        self.assertEqual(self.rc, 0 if all_passed else 1)

    def test_acceptance_doc_and_bench_stay_in_sync(self):
        """文档里承诺的 G1–G6，bench 必须一条不少——防止改了判据忘了文档。"""
        doc = (ROOT / "docs" / "ACCEPTANCE.md").read_text(encoding="utf-8")
        for gid in ("G1", "G2", "G3", "G4", "G5", "G6"):
            self.assertIn(gid, doc, f"ACCEPTANCE.md 缺 {gid}")
            self.assertTrue(any(gid in c["id"] for c in self.report["checks"]),
                            f"bench 缺 {gid} 对应的检查")

    def test_report_file_written(self):
        reports = sorted((ROOT / "reports").glob("bench-*.json"))
        self.assertTrue(reports, "bench 没有落报告文件")


if __name__ == "__main__":
    unittest.main()