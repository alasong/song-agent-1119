"""造检查器的准入：取代码块要取全、三反例不过就不许返回半成品。

这一段是「判定权交给样例」的执行侧：生成的检查器必须同时
放行合格件（含子标题那种）、拒收缺件与冒充件，且超时要当场算拒收而不是挂住。
"""
import tempfile
import unittest
from pathlib import Path

from sa2.forge import tools as ft


def fake_llm(code: str):
    return lambda messages, max_tokens=0, **kw: code


class ExtractCodeTest(unittest.TestCase):
    def test_greedy_to_the_last_fence(self):
        """检查器源码本身含 ``` 字面量：非贪婪会在第一个字面量处截断成语法错误。"""
        raw = "```python\na = 1\n```\n说明\n```\nb = 2\n```\n"
        self.assertEqual(ft._extract_code(raw), "a = 1\n```\n说明\n```\nb = 2")

    def test_unclosed_fence_still_returns_code(self):
        self.assertEqual(ft._extract_code("```python\nprint('hi')\n"), "print('hi')")


class GenerateCheckerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "tools"

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_entries_is_refused(self):
        with self.assertRaisesRegex(ValueError, "没有可检查的条目"):
            ft.generate_checker("目标", [], fake_llm("x"), self.out)

    def test_empty_model_output_is_refused(self):
        with self.assertRaisesRegex(ValueError, "没有输出代码块"):
            ft.generate_checker("目标", ["## 一、a"], fake_llm(""), self.out)

    def test_checker_that_rejects_everything_never_ships(self):
        with self.assertRaisesRegex(ValueError, "工具未通过三反例") as caught:
            ft.generate_checker("目标", ["## 一、a"], fake_llm("import sys\nsys.exit(1)\n"),
                                self.out)
        self.assertIn("合格件", str(caught.exception))
        self.assertFalse((self.out / "checker.py").exists(), "不达标就删掉，不留半成品")

    def test_hanging_checker_is_falsified_not_waited_on(self):
        code = "import time\ntime.sleep(30)\n"
        with self.assertRaisesRegex(ValueError, "超时"):
            ft.generate_checker("目标", ["## 一、a"], fake_llm(code), self.out, timeout=0.2)


class CheckerFromSectionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "tools"

    def tearDown(self):
        self.tmp.cleanup()

    def test_sample_without_headings_is_refused(self):
        with self.assertRaisesRegex(ValueError, "没有 .## . 标题"):
            ft.checker_from_sections("只有正文，没有标题。", self.out)

    def test_sample_that_its_own_checker_rejects_is_refused(self):
        """样例是最小合格件：检查器连它都判红 ⇒ 下限定得太高，不许出厂。"""
        with self.assertRaisesRegex(ValueError, "未通过三反例"):
            ft.checker_from_sections("## 一、a\n短", self.out)
        self.assertFalse((self.out / "sections_checker.py").exists())

    def test_good_sample_produces_a_checker(self):
        path, crit = ft.checker_from_sections("## 一、a\n" + "正文" * 50, self.out)
        self.assertTrue(path.is_file())
        self.assertEqual(crit.kind, "exec")
        self.assertTrue(crit.self_tested)


if __name__ == "__main__":
    unittest.main()