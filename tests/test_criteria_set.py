"""判据组自测：单条能过 ≠ 一组有判别力。

最贵的失效形态不是「判据写错」，而是「章节判据全过、要素判据没生效」——
标题齐全的空文档照样毕业。`test_set` 用三反例 + 空壳件 + 样例自证把四种失效打成红，
`tested_set` 任何一条红就拒绝整组进登记。
"""
import unittest
from unittest import mock

from sa2.core.judge import Judge
from sa2.forge import criteria as fc
from sa2.forge.criteria import Criterion


def sections(*heads):
    return fc.propose_sections("章节", list(heads), ("correctness",))


def content(*words):
    return fc.propose_content("要素", list(words), ("correctness",))


class TestSetTest(unittest.TestCase):
    def test_good_set_passes(self):
        specs = [sections("## 一、a", "## 二、b"), content("机制：", "止损：")]
        ok, fails = fc.test_set(specs)
        self.assertTrue(ok, fails)

    def test_empty_set_is_not_a_set(self):
        self.assertEqual(fc.test_set([]), (False, ["没有任何判据"]))

    def test_sections_only_set_is_meaningless(self):
        """只有章节判据：空壳件（标题齐全、正文「本节略」）照样过 ⇒ 这组判据没有判别力。"""
        ok, fails = fc.test_set([sections("## 一、a")])
        self.assertFalse(ok)
        self.assertTrue(any("空壳件" in f for f in fails), fails)

    def test_meaningless_set_lets_the_shell_through(self):
        """要素词恰好出现在「本节略」里：空壳件全过，说明这组判据没有判别力。"""
        ok, fails = fc.test_set([sections("## 一、a"), content("本节略")])
        self.assertFalse(ok)
        self.assertTrue(any("空壳件" in f for f in fails), fails)

    def test_tested_set_refuses_a_failing_group(self):
        with self.assertRaisesRegex(ValueError, "这组判据自测未过"):
            fc.tested_set([sections("## 一、a"), content("本节略")])

    def test_tested_set_marks_every_criterion(self):
        specs = fc.tested_set([sections("## 一、a", "## 二、b"), content("机制：")])
        self.assertTrue(all(c.self_tested for c in specs))

    def test_sample_that_the_group_rejects_is_red(self):
        """模型自己给的「合格样例」都过不了这组判据 ⇒ 判据不可满足或样例不达标。"""
        ok, fails = fc.test_set([sections("## 一、a", "## 二、b")], sample="随便一段没有标题的话")
        self.assertFalse(ok)
        self.assertTrue(any("样例自证" in f for f in fails), fails)

    def test_loose_judge_makes_the_good_case_fail(self):
        """判据连合格件都拒 ⇒ 合格件该过没过，必须红。"""
        specs = [sections("## 一、a", "## 二、b")]
        with mock.patch.object(Judge, "_run_sections", lambda self, spec, text: ["不认"]):
            ok, fails = fc.test_set(specs)
        self.assertFalse(ok)
        self.assertTrue(any("合格件" in f for f in fails), fails)

    def test_judge_that_ignores_everything_is_caught_by_three_cases(self):
        """判据恒过（不管正文长什么样）：缺件、冒充件、空壳件三条都要红。"""
        specs = [sections("## 一、a", "## 二、b"), content("机制：")]
        with mock.patch.object(Judge, "_run_sections", lambda self, spec, text: []), \
                mock.patch.object(Judge, "_run_regex", lambda self, spec, text: []):
            ok, fails = fc.test_set(specs)
        self.assertFalse(ok)
        for word in ("缺件", "冒充件", "空壳件"):
            self.assertTrue(any(word in f for f in fails), (word, fails))

    def test_unsupported_kind_says_so(self):
        crit = Criterion(name="引用", kind="citations", spec={}, dims=("correctness",))
        ok, fails = fc.self_test(crit)
        self.assertFalse(ok)
        self.assertTrue(any("自测暂不支持" in f for f in fails), fails)


if __name__ == "__main__":
    unittest.main()