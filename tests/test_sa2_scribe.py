"""sa2 的模型接入层：提示词必须把「上次错在哪」传给重做。"""
from __future__ import annotations

import unittest

from sa2.forge.org import Role
from sa2.forge.scribe import Scribe


def role(name="执行", kind="executor", duty="写正文", criteria="三节齐全"):
    return Role(name=name, kind=kind, duty=duty, criteria=criteria, budget=100)


class FakeLLM:
    def __init__(self, text="## 一、a\n"):
        self.text = text
        self.calls: list[tuple[list, int]] = []

    def __call__(self, messages, max_tokens=1000):
        self.calls.append((messages, max_tokens))
        return self.text


class ScribeTest(unittest.TestCase):
    def test_prompt_carries_role_stage_and_first_attempt(self):
        llm = FakeLLM()
        prompt = Scribe(llm).prompt(role(), "起草", "", 1)
        self.assertIn("写正文", prompt)
        self.assertIn("三节齐全", prompt)
        self.assertIn("起草", prompt)
        self.assertIn("第 1 次尝试", prompt)
        self.assertIn("（无，你是第一个）", prompt)

    def test_retry_prompt_carries_the_reject_reason(self):
        prompt = Scribe(FakeLLM()).prompt(role(), "成稿", "上游内容", 2, "缺章节：## 三、止损")
        self.assertIn("第 2 次尝试", prompt)
        self.assertIn("缺章节：## 三、止损", prompt)

    def test_no_feedback_section_on_first_attempt(self):
        prompt = Scribe(FakeLLM()).prompt(role(), "起草", "", 1)
        self.assertNotIn("上次被拒", prompt)

    def test_upstream_is_truncated(self):
        prompt = Scribe(FakeLLM(), upstream_chars=10).prompt(role(), "成稿", "x" * 100, 1)
        self.assertIn("x" * 10, prompt)
        self.assertNotIn("x" * 11, prompt)

    def test_verifier_produces_nothing_and_does_not_call_the_model(self):
        llm = FakeLLM()
        out = Scribe(llm)(role(kind="verifier", duty="只判", criteria="有结论"), "成稿", "", 1)
        self.assertEqual(out, "")
        self.assertEqual(llm.calls, [])
        self.assertEqual(Scribe(llm).calls, 0)

    def test_max_tokens_is_forwarded(self):
        llm = FakeLLM()
        Scribe(llm, max_tokens=321)(role(), "起草", "", 1)
        self.assertEqual(llm.calls[0][1], 321)

    def test_empty_model_output_is_normalised_to_empty_string(self):
        llm = FakeLLM(text=None)
        self.assertEqual(Scribe(llm)(role(), "起草", "", 1), "")

    def test_stage_requirements_are_visible_to_the_producer(self):
        """判据对生成方必须可见：看不见要求只能猜，猜不中就红两次。"""
        prompt = Scribe(FakeLLM()).prompt(role(), "成稿", "", 1, "",
                                          "必须包含：## 三、止损\n必须出现：止损线")
        self.assertIn("本阶段的验收要求", prompt)
        self.assertIn("## 三、止损", prompt)
        self.assertIn("止损线", prompt)



if __name__ == "__main__":
    unittest.main()