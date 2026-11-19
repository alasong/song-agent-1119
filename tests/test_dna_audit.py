"""DNA 审计的自检：钉住两件已实测踩过的事，以及「新增 DNA 必须带判据」这条门。"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import dna_audit


class ParseTest(unittest.TestCase):
    def test_reads_all_nine_from_the_design_doc(self):
        rows = dna_audit.parse_dna()
        self.assertEqual([r["num"] for r in rows], list(range(1, 10)))
        names = [r["name"] for r in rows]
        self.assertIn("交付可自证", names)

    def test_every_dna_has_a_registered_probe(self):
        """加了 DNA 却忘了登记判据，等于加了一句口号。"""
        missing = [r["num"] for r in dna_audit.parse_dna() if r["num"] not in dna_audit.SPEC]
        self.assertEqual(missing, [])

    def test_unknown_dna_is_reported_not_silently_passed(self):
        doc = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
        doc.write("## 二、核心DNA\n\n| # | DNA | 含义 | 落地形式 |\n|---|---|---|---|\n"
                  "| 10 | 维度声明 | 覆盖维度 | 词表 |\n\n## 三、别处\n")
        doc.close()
        try:
            result = dna_audit.audit(Path(doc.name))
        finally:
            Path(doc.name).unlink()
        self.assertEqual(result["unprobed"], [10])
        self.assertEqual(result["rows"][0]["status"], "unprobed")


class StatusTest(unittest.TestCase):
    def test_boundaries(self):
        f = lambda ok: {"ok": ok}
        self.assertEqual(dna_audit.status_of([]), "unprobed")
        self.assertEqual(dna_audit.status_of([f(True), f(True)]), "landed")
        self.assertEqual(dna_audit.status_of([f(False), f(False)]), "absent")
        self.assertEqual(dna_audit.status_of([f(True), f(False)]), "partial")

    def test_counts_cover_every_row(self):
        result = dna_audit.audit()
        self.assertEqual(sum(result["counts"].values()), len(result["rows"]))

    def test_result_is_recomputed_from_predicates_not_hardcoded(self):
        """故意改坏一条判据，那一条必须跟着变红——否则结论是写死的，不是量出来的。"""
        original = dna_audit.SPEC[4]
        dna_audit.SPEC[4] = [("注入的永假断言", lambda: (False, "注入"))]
        try:
            result = dna_audit.audit()
        finally:
            dna_audit.SPEC[4] = original
        row = next(r for r in result["rows"] if r["num"] == 4)
        self.assertEqual(row["status"], "absent")


class CodeLinesTest(unittest.TestCase):
    """判据只看代码：注释与字符串里的词不算实现（首版三处假绿就是这么来的）。"""

    def _file(self, body: str) -> Path:
        t = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
        t.write(body)
        t.close()
        self.addCleanup(lambda: Path(t.name).unlink())
        return Path(t.name)

    def test_comment_mentioning_a_capability_is_not_implementation(self):
        p = self._file("def f():\n    # 这里将来做回滚\n    return 1\n")
        code = "\n".join(text for _, text in dna_audit.code_lines(p))
        self.assertNotIn("回滚", code)
        self.assertIn("return", code)

    def test_string_literal_is_not_implementation(self):
        p = self._file('NAMES = ["目标偏离度"]\n')
        code = "\n".join(text for _, text in dna_audit.code_lines(p))
        self.assertNotIn("偏离度", code)

    def test_punctuation_is_preserved_so_call_patterns_still_match(self):
        p = self._file("def check(text):\n    return delivery.check(text)\n")
        code = "\n".join(text for _, text in dna_audit.code_lines(p))
        self.assertIn("def check(text):", code)
        self.assertIn("delivery.check(text)", code)

    def test_line_numbers_survive_blanking(self):
        p = self._file("# a\n# b\nx = 1\n")
        rows = dna_audit.code_lines(p)
        self.assertEqual(rows[-1][0], 3)
        self.assertIn("x = 1", rows[-1][1])


class CommandTest(unittest.TestCase):
    def test_exit_code_is_zero_when_every_dna_has_a_probe(self):
        proc = subprocess.run([sys.executable, "scripts/dna_audit.py", "--json"],
                              capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        self.assertIn('"rows"', proc.stdout)

    def test_exit_code_is_one_when_doc_has_an_unprobed_dna(self):
        doc = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
        doc.write("## 二、核心DNA\n\n| # | DNA | 含义 | 落地形式 |\n|---|---|---|---|\n"
                  "| 10 | 维度声明 | 覆盖维度 | 词表 |\n\n## 三、别处\n")
        doc.close()
        try:
            proc = subprocess.run([sys.executable, "scripts/dna_audit.py", "--doc", doc.name],
                                  capture_output=True, text=True,
                                  cwd=Path(__file__).resolve().parents[1])
        finally:
            Path(doc.name).unlink()
        self.assertEqual(proc.returncode, 1, proc.stdout[-400:])
        self.assertIn("未登记判据", proc.stdout)


if __name__ == "__main__":
    unittest.main()