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

    def test_ritual_sentence_without_numbers_is_red(self):
        """「候选集内最优」这种空话必须判红——它借了论证的词，没给可核对的数。"""
        self.write("docs/x.md", "本方案在候选集内最优。\n")
        result = run_checker(self.root)
        self.assertEqual(result["rc"], 1)
        self.assertEqual(result["problems"][0]["kind"], "bare-optimal")

    def test_claim_with_reading_passes(self):
        self.write("docs/x.md", "候选 3 个，选中方案少 2 次调用，L1 占优。\n")
        self.assertEqual(run_checker(self.root)["rc"], 0)

    def test_candidate_set_word_alone_no_longer_passes(self):
        """这一条是补丁的回归：只写「候选集」不给数，必须仍然判红。"""
        self.write("docs/x.md", "结论：候选集内最优，预算充足，差值另附。\n")
        self.assertEqual(run_checker(self.root)["rc"], 1)

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

class OpenTailTest(unittest.TestCase):
    """交付里不许留「下一步 / 待办」节（口径同 ~/.dsh/notes/work-loop.md）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "reports").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_next_step_heading_is_red(self):
        (self.root / "docs" / "x.md").write_text("# x\n\n## 下一步\n\n- 以后再补\n", encoding="utf-8")
        result = run_checker(self.root)
        self.assertEqual(result["rc"], 1)
        self.assertEqual(result["problems"][0]["kind"], "open-tail")

    def test_todo_heading_in_any_level_is_red(self):
        (self.root / "docs" / "x.md").write_text("### 待办\n\n- 排队\n", encoding="utf-8")
        self.assertEqual(run_checker(self.root)["rc"], 1)

    def test_body_text_mentioning_it_is_fine(self):
        (self.root / "docs" / "x.md").write_text("正文提到「待办」这个词不算留尾巴。\n",
                                                 encoding="utf-8")
        self.assertEqual(run_checker(self.root)["rc"], 0)
