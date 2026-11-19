"""交付标准机检自身的测试：能判红才有意义。

四条必须分开验：
- 裸称「最优」→ 红；
- 引号里讨论这个词 → 不判（否则没人敢写规则本身）；
- 代码块里 → 不判；
- 报告判定与读数不符 → 红（自己给自己发奖状正是要防的）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_checker(root: Path) -> dict:
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "claim_check.py"),
                           "--json", "--root", str(root)],
                          cwd=ROOT, capture_output=True, text=True)
    return {"rc": proc.returncode, **json.loads(proc.stdout)}


class BareOptimalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "reports").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, text: str) -> None:
        (self.root / rel).write_text(text, encoding="utf-8")

    def test_bare_claim_is_red(self):
        self.write("docs/x.md", "这套方案是最优的。\n")
        result = run_checker(self.root)
        self.assertEqual(result["rc"], 1)
        self.assertEqual(result["problems"][0]["kind"], "bare-optimal")

    def test_quoted_discussion_is_allowed(self):
        self.write("docs/x.md", "「最优」这个词不可证，所以换成 L1 占优。\n")
        self.assertEqual(run_checker(self.root)["rc"], 0, "不许写规则本身，规则就执行不了")

    def test_code_block_is_allowed(self):
        self.write("docs/x.md", "```\n旧标准要求写：为什么这是最优解\n```\n")
        self.assertEqual(run_checker(self.root)["rc"], 0)

    def test_level_qualifier_makes_it_pass(self):
        self.write("docs/x.md", "结论：候选集内 L1 占优（候选 3 个）。\n")
        self.assertEqual(run_checker(self.root)["rc"], 0)

    def test_candidate_set_qualifier_makes_it_pass(self):
        self.write("docs/x.md", "只在这三个候选集内是最优的。\n")
        self.assertEqual(run_checker(self.root)["rc"], 0)

    def test_overclaim_words_are_red(self):
        self.write("docs/x.md", "这项能力已经完全验证。\n")
        result = run_checker(self.root)
        self.assertEqual(result["rc"], 1)
        self.assertEqual(result["problems"][0]["kind"], "certainty")


class BenchVerdictTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "reports").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def report(self, passed: int, total: int, verdict: str) -> None:
        (self.root / "reports" / "bench-20260101-000000.json").write_text(
            json.dumps({"passed": passed, "total": total, "verdict": verdict}), encoding="utf-8")

    def test_honest_verdict_passes(self):
        self.report(5, 6, "不够")
        self.assertEqual(run_checker(self.root)["rc"], 0)

    def test_self_award_is_red(self):
        self.report(5, 6, "够了")
        result = run_checker(self.root)
        self.assertEqual(result["rc"], 1)
        self.assertEqual(result["problems"][0]["kind"], "verdict-mismatch")

    def test_broken_report_is_red_not_skipped(self):
        (self.root / "reports" / "bench-x.json").write_text("{不是 JSON", encoding="utf-8")
        result = run_checker(self.root)
        self.assertEqual(result["rc"], 1)
        self.assertEqual(result["problems"][0]["kind"], "broken-report")


class RepoIsCleanTest(unittest.TestCase):
    def test_this_repo_passes(self):
        result = run_checker(ROOT)
        self.assertEqual(result["rc"], 0,
                         f"仓库里有裸称或判定不符：{result['problems']}")


if __name__ == "__main__":
    unittest.main()