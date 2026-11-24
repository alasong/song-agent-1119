"""模型请求体的形状：extra 必须并进 body（关思维链靠它），usage 变体也要带。

`test_llm_retry` 盖的是重试；这里把 `_post` 换成捕获器，只看「发出去的 body 是什么」。
这一段是唯一能证明「worker 里关掉 thinking」真的发出去了的地方。
"""
import unittest
from unittest import mock

from sa2 import llm


class RequestBodyTest(unittest.TestCase):
    def capture(self, response: dict) -> dict:
        seen: dict = {}

        def fake_post(body, timeout):
            seen.update(body)
            return response

        self._patch = mock.patch.object(llm, "_post", fake_post)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        return seen

    def test_complete_with_extra_merges_it(self):
        seen = self.capture({"choices": [{"message": {"content": "正文"}}]})
        out = llm.complete([{"role": "user", "content": "hi"}],
                           extra={"thinking": {"type": "disabled"}})
        self.assertEqual(out, "正文")
        self.assertEqual(seen["thinking"], {"type": "disabled"})
        self.assertEqual(seen["model"], llm.DEFAULT_MODEL)
        self.assertTrue(seen["max_tokens"] > 0)

    def test_complete_without_extra_has_no_thinking_key(self):
        seen = self.capture({"choices": [{"message": {"content": "正文"}}]})
        llm.complete([{"role": "user", "content": "hi"}])
        self.assertNotIn("thinking", seen)

    def test_complete_usage_merges_extra_and_returns_usage(self):
        seen = self.capture({"choices": [{"message": {"content": "正文"}}],
                             "usage": {"total_tokens": 12}})
        text, usage = llm.complete_usage([{"role": "user", "content": "hi"}],
                                         extra={"thinking": {"type": "disabled"}})
        self.assertEqual(text, "正文")
        self.assertEqual(usage, {"total_tokens": 12})
        self.assertEqual(seen["thinking"], {"type": "disabled"})


if __name__ == "__main__":
    unittest.main()