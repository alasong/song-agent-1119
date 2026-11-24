"""worker 作业契约：派活的作业是模块级函数，回传形状固定。

这些函数在子进程里被 `import` 执行（`sa2/loop/workers.py::_run_job`），
所以它们自己的形状就是接口：返回值、异常、usage 键。进程内单测直接打这一层，
比每次起两个真进程便宜，也能把「哪个分支返回什么」钉死。
"""
import unittest
from datetime import datetime
from unittest import mock

from sa2.loop import jobs


class SimpleJobsTest(unittest.TestCase):
    def test_echo_returns_input(self):
        self.assertEqual(jobs.echo("你好"), "你好")

    def test_slow_sleeps_then_returns(self):
        started = datetime.now()
        self.assertEqual(jobs.slow(0.01, "完成"), "完成")
        self.assertGreaterEqual((datetime.now() - started).total_seconds(), 0.01)

    def test_boom_raises_with_message(self):
        with self.assertRaisesRegex(RuntimeError, "炸了"):
            jobs.boom("炸了")


class LlmJobsTest(unittest.TestCase):
    def test_fake_llm_echoes_last_message_with_usage(self):
        out = jobs.fake_llm([{"role": "user", "content": "写一段"},
                             {"role": "user", "content": "第二段"}])
        self.assertEqual(out["text"], "第二段")
        self.assertEqual(out["usage"], {"total_tokens": 7})

    def test_section_llm_splits_by_stage_name(self):
        draft = jobs.section_llm([{"role": "user", "content": "请起草"}])
        final = jobs.section_llm([{"role": "user", "content": "请成稿"}])
        self.assertEqual(draft["text"].count("## "), 2)
        self.assertEqual(final["text"].count("## "), 3)
        self.assertEqual(draft["usage"]["total_tokens"], 11)

    def test_real_llm_job_returns_text_and_usage(self):
        seen = {}

        def fake_usage(messages, **kw):
            seen.update(kw)
            return "正文", {"total_tokens": 9}

        with mock.patch("sa2.llm.complete_usage", side_effect=fake_usage):
            out = jobs.llm_complete([{"role": "user", "content": "x"}], max_tokens=10)
        self.assertEqual(out, {"text": "正文", "usage": {"total_tokens": 9}})
        self.assertEqual(seen["max_tokens"], 10)
        self.assertEqual(seen["extra"], {"thinking": {"type": "disabled"}},
                         "worker 里调模型必须关掉思维链，否则预算全烧在思维上")

    def test_real_llm_job_survives_empty_content(self):
        with mock.patch("sa2.llm.complete_usage", return_value=(None, None)):
            out = jobs.llm_complete([{"role": "user", "content": "x"}])
        self.assertEqual(out, {"text": "", "usage": {}})

    def test_fail_llm_raises_the_pipeline_error(self):
        with self.assertRaisesRegex(RuntimeError, "模型通道断了"):
            jobs.fail_llm([{"role": "user", "content": "x"}])


if __name__ == "__main__":
    unittest.main()