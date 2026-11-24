"""目标拆解的拒收面：模型输出不合 JSON、子任务缺交付物、重名，都必须当场拒。

`test_sa2_forge.GoalTest` 盖了维度词表与个数上限；这里补形状与重名，
并钉住 decompose 把词表与上限原样带进提示词（拆解是环的第一步，错在这里后面全错）。
"""
import json
import unittest

from sa2.forge import dims as fd
from sa2.forge import goal as fg

VOCAB = tuple(fd.VOCAB)


def raw(items) -> str:
    return "前置说明\n" + json.dumps({"subtasks": items}, ensure_ascii=False)


def item(name="a", deliverable="文档", dims=("correctness",)):
    return {"name": name, "deliverable": deliverable, "dims": list(dims)}


class GoalParseTest(unittest.TestCase):
    def test_no_json_in_output(self):
        with self.assertRaisesRegex(fg.GoalError, "没有 JSON"):
            fg.parse("目标", "模型说：这个目标不用拆", VOCAB)

    def test_broken_json_is_named(self):
        with self.assertRaisesRegex(fg.GoalError, "JSON 解析失败"):
            fg.parse("目标", "{不是 JSON}", VOCAB)

    def test_missing_deliverable_is_named(self):
        with self.assertRaisesRegex(fg.GoalError, "缺 name/deliverable"):
            fg.parse("目标", raw([item(deliverable="")]), VOCAB)

    def test_duplicate_subtask_name_is_refused(self):
        with self.assertRaisesRegex(fg.GoalError, "子任务重名"):
            fg.parse("目标", raw([item("a"), item("a", deliverable="实验")]), VOCAB)

    def test_good_items_are_parsed(self):
        subs = fg.parse("目标", raw([item("a"), item("b", "实验")]), VOCAB)
        self.assertEqual([s.name for s in subs], ["a", "b"])
        self.assertEqual(subs[0].dims, ("correctness",))


class DecomposeTest(unittest.TestCase):
    def test_prompt_carries_vocab_and_limit(self):
        prompts = []

        def llm(messages, **kw):
            prompts.append(messages[-1]["content"])
            return raw([item()])

        subs = fg.decompose("写一份报告", llm, VOCAB, max_n=3)
        self.assertEqual(len(subs), 1)
        self.assertIn("写一份报告", prompts[0])
        self.assertIn("1–3 个子任务", prompts[0])
        for dim in ("correctness", "security"):
            self.assertIn(dim, prompts[0])

    def test_bad_model_output_propagates(self):
        with self.assertRaises(fg.GoalError):
            fg.decompose("目标", lambda messages, **kw: "不好意思，拆不了", VOCAB)


if __name__ == "__main__":
    unittest.main()