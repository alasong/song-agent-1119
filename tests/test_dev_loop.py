"""M1：代码工单回路。红先：sa2/loop/dev.py 还不存在。

判据：改到绿；失败轮带着测试输出重做；改动只在声明路径内（越界一次模型都不调）。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from sa2.core.ledger import Ledger
from sa2.loop.dev import DevLoop, DevRefused, DevTicket

BAD = "```python\ndef add(a, b):\n    return 0\n```"
GOOD = "```python\ndef add(a, b):\n    return a + b\n```"


class DevLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "src.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")
        (self.root / "test_demo.py").write_text(
            "import unittest\nfrom src import add\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n", encoding="utf-8")
        self.ledger = Ledger(self.root / "ledger.jsonl")
        self.ticket = DevTicket(
            id="t1", goal="让 test_demo 变绿", target="src.py",
            test_cmd=[sys.executable, "-m", "unittest", "test_demo", "-q"],
            max_rounds=3)

    def tearDown(self):
        self.tmp.cleanup()

    def _loop(self, llm):
        return DevLoop(llm, self.ledger, self.root)

    def test_green_on_first_round(self):
        out = self._loop(lambda messages, max_tokens=None: GOOD).run(self.ticket)
        self.assertTrue(out["passed"], out)
        self.assertEqual(out["rounds"], 1)
        self.assertIn("return a + b", (self.root / "src.py").read_text(encoding="utf-8"))
        self.assertEqual(self.ledger.count("dev_test"), 1)

    def test_failed_round_feeds_the_test_output_back(self):
        prompts: list[str] = []
        replies = iter([BAD, GOOD])

        def llm(messages, max_tokens=None):
            prompts.append(messages[0]["content"])
            return next(replies)

        out = self._loop(llm).run(self.ticket)
        self.assertTrue(out["passed"], out)
        self.assertEqual(out["rounds"], 2)
        self.assertIn("FAILED", prompts[1] + " " + prompts[0] + " " + prompts[1],
                      "第二轮必须带着上一轮的测试失败输出")
        self.assertIn("AssertionError", prompts[1])
        self.assertEqual(self.ledger.count("dev_test"), 2)

    def test_target_outside_root_is_refused_before_any_call(self):
        calls: list[int] = []
        outside = replace(self.ticket, target="../evil.py")
        with self.assertRaises(DevRefused):
            self._loop(lambda m, max_tokens=None: calls.append(1) or GOOD).run(outside)
        self.assertEqual(calls, [], "越界请求一次模型都不许调")

    def test_ticket_without_test_command_is_refused(self):
        with self.assertRaises(DevRefused):
            self._loop(lambda m, max_tokens=None: GOOD).run(replace(self.ticket, test_cmd=[]))

    def test_rounds_are_capped_and_failure_is_loud(self):
        out = self._loop(lambda messages, max_tokens=None: BAD).run(
            replace(self.ticket, max_rounds=2))
        self.assertFalse(out["passed"])
        self.assertEqual(out["rounds"], 2)
        self.assertEqual(self.ledger.count("dev_failed"), 1)


if __name__ == "__main__":
    unittest.main()