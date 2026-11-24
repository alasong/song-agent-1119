"""让系统自己出判据：规格 + 样例两个块要拆得开，切章节切不动时要明说不切。

`test_sa2_forge` 盖的是 instantiate/self_test；这里补 propose_spec（模型出口）
与 plan_slices 的空手分支——判据来源那一步没人跑过，等于「自己出判据」没被验。
"""
import unittest

from sa2.forge import criteria as fc


class ProposeSpecTest(unittest.TestCase):
    def test_two_blocks_are_split(self):
        raw = ("### SPEC\n必须包含：## 一、a\n必须出现：机制：\n"
               "### SAMPLE\n## 一、a\n正文里有机制：\n")
        prompts = []

        def llm(messages, max_tokens=None):
            prompts.append(messages[-1]["content"])
            return raw

        out = fc.propose_spec("写一份报告", llm, context="上次交付缺小节")
        self.assertIn("必须包含：## 一、a", out["spec"])
        self.assertIn("正文里有机制", out["sample"])
        self.assertIn("写一份报告", prompts[0])
        self.assertIn("上次交付缺小节", prompts[0], "上下文要进提示词")

    def test_plain_text_falls_back_to_raw_spec(self):
        out = fc.propose_spec("目标", lambda m, max_tokens=None: "没有分块的一段话")
        self.assertEqual(out["spec"], "没有分块的一段话")
        self.assertEqual(out["sample"], "")

    def test_empty_model_output_is_not_a_crash(self):
        out = fc.propose_spec("目标", lambda m, max_tokens=None: "")
        self.assertEqual(out["raw"], "")


class PlanSlicesTest(unittest.TestCase):
    def test_no_stages_means_no_slices(self):
        self.assertEqual(fc.plan_slices(["## 一、a"], 0), [])

    def test_no_headings_means_no_slices(self):
        self.assertEqual(fc.plan_slices([], 2), [])

    def test_headings_are_split_in_order_without_loss(self):
        heads = ["## 一、a", "## 二、b", "## 三、c"]
        chunks = fc.plan_slices(heads, 2)
        self.assertEqual(sum(chunks, []), heads, "切开不许丢标题也不许改顺序")
        self.assertTrue(all(chunk for chunk in chunks))


if __name__ == "__main__":
    unittest.main()